"""Publish the pre-generated days into the live AWS sources.

    python -m data_generator.publish                          # every pending day up to yesterday (UTC)
    python -m data_generator.publish --through 2026-11-10 --max-days 10

The simulator bucket holds one folder per day under ``days/`` (written by ``data_generator.daily``)
and ``state/published_through`` with the last day already published. A run starts the shared RDS
instance and SFTP server if they are stopped, then applies every pending day in order:

- CaseDesk: rows are upserted by primary key, one transaction per day
- activity tracker: segment documents are put into DynamoDB
- S3: files are copied into the sources bucket
- SFTP: files are uploaded as ``<name>.part`` and renamed, so a reader never sees half a file

Every write replaces by key, so publishing a day twice is harmless, and the watermark moves only
after a batch is fully written. Several pending days (the first load, or catching up after missed
runs) go in batches; within a batch DynamoDB gets only the last version of each segment, since
nobody could have read the versions in between.

The database, its schema and the read-only login are created by Terraform; the publisher creates
the tables (as their owner, so the reader's default privileges apply).

Connection details come from SSM Parameter Store; AWS credentials from the usual boto3 chain.
This follows the RetailPulse publisher, including its keepalives and statement timeouts.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import time
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .sources.casedesk import LOAD_ORDER, TABLE_COLUMNS

log = logging.getLogger("supporthub.publish")

DAYS_PREFIX = "days/"
STATE_KEY = "state/published_through"
SCHEMA_SQL = Path(__file__).parent / "sources" / "casedesk_schema.sql"


def upsert_sql(table: str, columns: list[str], staging: str) -> str:
    """INSERT ... ON CONFLICT on the first column, which is the primary key of every table."""
    column_list = ", ".join(columns)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns[1:])
    return (
        f"INSERT INTO casedesk.{table} ({column_list}) SELECT {column_list} FROM {staging} "
        f"ON CONFLICT ({columns[0]}) DO UPDATE SET {updates}"
    )


def target_for(key: str, day: date) -> tuple[str, str]:
    """Where an object of a day folder goes: ("casedesk", table), ("segments", ""),
    ("s3", key in the sources bucket) or ("sftp", path under the SFTP user's home)."""
    rel = key.removeprefix(f"{DAYS_PREFIX}{day.isoformat()}/")
    kind, _, rest = rel.partition("/")
    if kind == "casedesk":
        return "casedesk", rest.removesuffix(".csv")
    if kind == "activity_api":
        return "segments", ""
    if kind in ("s3", "sftp"):
        return kind, rest
    raise ValueError(f"unexpected object {key}")


def batches(days: list[date], size: int) -> list[list[date]]:
    return [days[i : i + size] for i in range(0, len(days), size)]


class Publisher:
    def __init__(self, session, parameter_prefix: str):
        self.session = session
        self.s3 = session.client("s3")
        self.params = self._read_parameters(parameter_prefix)
        self.simulator_bucket = self.params["s3/simulator_bucket"]
        self.sources_bucket = self.params["s3/sources_bucket"]

    def _read_parameters(self, prefix: str) -> dict[str, str]:
        params = {}
        pages = self.session.client("ssm").get_paginator("get_parameters_by_path")
        for page in pages.paginate(Path=prefix, Recursive=True, WithDecryption=True):
            for p in page["Parameters"]:
                params[p["Name"].removeprefix(prefix).lstrip("/")] = p["Value"]
        return params

    # ------------------------------------------------------------------ state
    def published_through(self) -> date | None:
        try:
            body = self.s3.get_object(Bucket=self.simulator_bucket, Key=STATE_KEY)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None
        return date.fromisoformat(body.decode().strip())

    def _set_published_through(self, day: date) -> None:
        self.s3.put_object(Bucket=self.simulator_bucket, Key=STATE_KEY, Body=day.isoformat().encode())

    def available_days(self) -> list[date]:
        days = []
        pages = self.s3.get_paginator("list_objects_v2")
        for page in pages.paginate(Bucket=self.simulator_bucket, Prefix=DAYS_PREFIX, Delimiter="/"):
            for prefix in page.get("CommonPrefixes", []):
                days.append(date.fromisoformat(prefix["Prefix"].removeprefix(DAYS_PREFIX).strip("/")))
        return sorted(days)

    def _day_keys(self, day: date) -> list[str]:
        keys = []
        pages = self.s3.get_paginator("list_objects_v2")
        for page in pages.paginate(Bucket=self.simulator_bucket, Prefix=f"{DAYS_PREFIX}{day.isoformat()}/"):
            keys += [obj["Key"] for obj in page.get("Contents", [])]
        return sorted(keys)

    def _read(self, key: str) -> bytes:
        return self.s3.get_object(Bucket=self.simulator_bucket, Key=key)["Body"].read()

    # ------------------------------------------------------------------ sources
    def ensure_sources_running(self, timeout_s: int = 1800) -> str:
        """Start the shared RDS instance and SFTP server if needed; return the SFTP server's IP."""
        rds, ec2 = self.session.client("rds"), self.session.client("ec2")
        db_id, instance_id = self.params["rds/instance_identifier"], self.params["sftp/instance_id"]
        deadline = time.monotonic() + timeout_s
        while True:
            db = rds.describe_db_instances(DBInstanceIdentifier=db_id)["DBInstances"][0]["DBInstanceStatus"]
            vm = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]
            vm_state = vm["State"]["Name"]
            if db == "stopped":
                log.info("starting RDS %s", db_id)
                rds.start_db_instance(DBInstanceIdentifier=db_id)
            if vm_state == "stopped":
                log.info("starting SFTP server %s", instance_id)
                ec2.start_instances(InstanceIds=[instance_id])
            if db == "available" and vm_state == "running" and vm.get("PublicIpAddress"):
                return vm["PublicIpAddress"]
            if time.monotonic() > deadline:
                raise TimeoutError(f"sources not ready: RDS {db}, SFTP {vm_state}")
            log.info("waiting for sources: RDS %s, SFTP %s", db, vm_state)
            time.sleep(30)

    def connect_postgres(self):
        import psycopg

        return psycopg.connect(
            host=self.params["postgres/host"],
            port=int(self.params["postgres/port"]),
            dbname=self.params["postgres/database"],
            user=self.params["postgres/username"],
            password=self.params["postgres/password"],
            sslmode="require",
            connect_timeout=20,
            autocommit=True,
            # Keepalives detect a silently dropped link, and the server gives up on any statement
            # or transaction that stalls (a RetailPulse catch-up once hung for 20 hours without them).
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=3,
            options="-c statement_timeout=300000 -c idle_in_transaction_session_timeout=300000",
        )

    @contextmanager
    def connect_sftp(self, host: str, attempts: int = 12):
        import paramiko

        key = paramiko.Ed25519Key.from_private_key(io.StringIO(self.params["sftp/private_key"]))
        for attempt in range(1, attempts + 1):
            client = paramiko.SSHClient()
            # The server is ours and its IP changes on every start, so there is no stable known_hosts.
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(
                    host,
                    port=int(self.params["sftp/port"]),
                    username=self.params["sftp/username"],
                    pkey=key,
                    timeout=20,
                    allow_agent=False,
                    look_for_keys=False,
                )
                break
            except (OSError, paramiko.SSHException) as exc:
                client.close()
                if attempt == attempts:
                    raise
                log.info("SFTP not ready yet (%s), retrying", exc)
                time.sleep(15)
        try:
            with client.open_sftp() as sftp:
                yield sftp
        finally:
            client.close()

    @staticmethod
    def setup_database(conn) -> None:
        """Create the CaseDesk tables if they are missing. Safe to run every time."""
        conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ publishing
    def publish(self, days: list[date], conn, sftp) -> dict[str, int]:
        counts = {"casedesk_rows": 0, "s3_files": 0, "sftp_files": 0, "segments": 0}
        segments: dict[str, dict] = {}
        for day in days:
            targets = [(key, *target_for(key, day)) for key in self._day_keys(day)]
            tables = {name: key for key, kind, name in targets if kind == "casedesk"}
            with conn.transaction():
                for table in LOAD_ORDER:
                    if table in tables:
                        started = time.perf_counter()
                        rows = self._upsert(conn, table, self._read(tables[table]))
                        counts["casedesk_rows"] += rows
                        log.debug("%s %s: %d rows in %.1fs", day, table, rows, time.perf_counter() - started)
            for key, kind, dest in targets:
                if kind == "s3":
                    self.s3.copy_object(
                        Bucket=self.sources_bucket,
                        Key=dest,
                        CopySource={"Bucket": self.simulator_bucket, "Key": key},
                    )
                    counts["s3_files"] += 1
                elif kind == "sftp":
                    self._upload(sftp, dest, self._read(key))
                    counts["sftp_files"] += 1
                elif kind == "segments":
                    for line in self._read(key).decode("utf-8").splitlines():
                        doc = json.loads(line, parse_float=Decimal)
                        segments[doc["segment_id"]] = doc
            log.info("published %s", day)
        counts["segments"] = self._put_segments(segments.values())
        self._set_published_through(days[-1])
        return counts

    @staticmethod
    def _upsert(conn, table: str, body: bytes) -> int:
        columns = TABLE_COLUMNS[table]
        staging = f"staging_{table}"
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE TEMP TABLE {staging} (LIKE casedesk.{table} INCLUDING DEFAULTS) ON COMMIT DROP"
            )
            copy_sql = f"COPY {staging} ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv, HEADER true)"
            with cur.copy(copy_sql) as copy:
                copy.write(body)
            cur.execute(upsert_sql(table, columns, staging))
            return cur.rowcount

    @staticmethod
    def _upload(sftp, path: str, body: bytes) -> None:
        folder = path.rsplit("/", 1)[0]
        try:
            sftp.stat(folder)
        except FileNotFoundError:
            sftp.mkdir(folder)
        sftp.putfo(io.BytesIO(body), f"{path}.part")
        sftp.posix_rename(f"{path}.part", path)

    def _put_segments(self, docs) -> int:
        table = self.session.resource("dynamodb").Table(self.params["dynamodb/segments_table"])
        n = 0
        with table.batch_writer(overwrite_by_pkeys=["segment_id"]) as writer:
            for doc in docs:
                # The API's index: the UTC day of updated_at (stored as ISO text in UTC). A running
                # segment keeps end_ts as a DynamoDB NULL, so the API still returns the key.
                writer.put_item(Item={**doc, "updated_day": doc["updated_at"][:10]})
                n += 1
        return n


def main(argv: list[str] | None = None) -> int:
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    parser = argparse.ArgumentParser(description="Publish pre-generated days into the AWS sources.")
    parser.add_argument("--through", type=date.fromisoformat, default=yesterday, help="last day to publish")
    parser.add_argument("--max-days", type=int, help="publish at most this many days in this run")
    parser.add_argument("--batch-days", type=int, default=31, help="days per batch when catching up")
    parser.add_argument("--parameter-prefix", default="/supporthub/dev")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--verbose", action="store_true", help="log every table of every day")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True)
    log.setLevel(logging.DEBUG if args.verbose else logging.INFO)

    import boto3

    publisher = Publisher(boto3.Session(region_name=args.region), args.parameter_prefix)
    done = publisher.published_through()
    pending = [d for d in publisher.available_days() if (done is None or d > done) and d <= args.through]
    if args.max_days:
        pending = pending[: args.max_days]
    if not pending:
        log.info("nothing to publish: published through %s, asked for %s", done, args.through)
        return 0
    log.info(
        "publishing %d days: %s to %s (previously through %s)", len(pending), pending[0], pending[-1], done
    )

    host = publisher.ensure_sources_running()
    with publisher.connect_postgres() as conn, publisher.connect_sftp(host) as sftp:
        publisher.setup_database(conn)
        for batch in batches(pending, args.batch_days):
            started = time.perf_counter()
            counts = publisher.publish(batch, conn, sftp)
            log.info(
                "batch %s to %s done in %.0fs: %s", batch[0], batch[-1], time.perf_counter() - started, counts
            )
    log.info("published through %s", pending[-1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
