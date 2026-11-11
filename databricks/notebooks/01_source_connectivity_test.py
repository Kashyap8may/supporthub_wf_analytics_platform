# Databricks notebook source
# MAGIC %md
# MAGIC # SupportHub: can Databricks reach every AWS source?
# MAGIC Uses the read-only `pipelines` IAM user from the `supporthub-dev` secret scope, reads the
# MAGIC connection details from Parameter Store, and touches each source once. It writes nothing.
# MAGIC The shared RDS instance and SFTP server must be running (06:00 to 08:00 UTC, or `make sources-up`).

# COMMAND ----------

# MAGIC %pip install --quiet paramiko "psycopg[binary]"

# COMMAND ----------

import io
import json

import boto3
import paramiko
import psycopg
import requests

SCOPE = "supporthub-dev"
PREFIX = "/supporthub/dev"

session = boto3.Session(
    aws_access_key_id=dbutils.secrets.get(SCOPE, "aws_access_key_id"),
    aws_secret_access_key=dbutils.secrets.get(SCOPE, "aws_secret_access_key"),
    region_name="us-east-1",
)
ssm = session.client("ssm")


def param(name, secret=False, prefix=PREFIX):
    return ssm.get_parameter(Name=f"{prefix}/{name}", WithDecryption=secret)["Parameter"]["Value"]


results = {}


def check(name, fn):
    try:
        results[name] = f"OK   {fn()}"
    except Exception as exc:
        results[name] = f"FAIL {type(exc).__name__}: {str(exc)[:200]}"


# COMMAND ----------


def s3_sources():
    resp = session.client("s3").list_objects_v2(Bucket=param("s3/sources_bucket"), MaxKeys=5)
    return f"listed sources bucket, {resp['KeyCount']} keys"


def restricted_parameters_are_hidden():
    # The pipelines user must not read the owner password or learn where the simulator keeps
    # the future; both reads should be refused.
    for name in ["postgres/password", "s3/simulator_bucket"]:
        try:
            param(name, secret=True)
        except ssm.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] != "AccessDeniedException":
                raise
        else:
            raise RuntimeError(f"pipelines user can read {name}")
    return "owner password and simulator bucket are refused, as intended"


def activity_api():
    resp = requests.get(
        param("activity_api/url"),
        params={"limit": 5},
        headers={"x-api-key": param("activity_api/api_key", secret=True)},
        timeout=20,
    )
    resp.raise_for_status()
    return f"HTTP {resp.status_code}, {len(resp.json()['activities'])} activities"


def postgres():
    with psycopg.connect(
        host=param("postgres/host"),
        port=int(param("postgres/port")),
        dbname=param("postgres/database"),
        user=param("postgres/reader_username"),
        password=param("postgres/reader_password", secret=True),
        sslmode="require",
        connect_timeout=15,
    ) as conn:
        schemas = [r[0] for r in conn.execute("select schema_name from information_schema.schemata")]
    return f"connected as reader; casedesk schema visible: {'casedesk' in schemas}"


def postgres_jdbc():
    url = f"jdbc:postgresql://{param('postgres/host')}:{param('postgres/port')}/{param('postgres/database')}"
    df = (
        spark.read.format("jdbc")
        .option("url", f"{url}?sslmode=require")
        .option("user", param("postgres/reader_username"))
        .option("password", param("postgres/reader_password", secret=True))
        .option("query", "select current_database() as db")
        .load()
    )
    return f"spark JDBC read database {df.collect()[0]['db']}"


def sftp():
    # The SFTP server is shared and its IP changes on every start; the parameter says where to look.
    host = ssm.get_parameter(Name=param("sftp/host_parameter"))["Parameter"]["Value"]
    key = paramiko.Ed25519Key.from_private_key(io.StringIO(param("sftp/private_key", secret=True)))
    with paramiko.SSHClient() as client:
        # Demo only: the host key changes if the server is rebuilt. Production would pin it.
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            host,
            port=int(param("sftp/port")),
            username=param("sftp/username"),
            pkey=key,
            timeout=15,
            allow_agent=False,
            look_for_keys=False,
        )
        with client.open_sftp() as channel:
            return f"listed {sorted(channel.listdir('.'))}, wfm: {sorted(channel.listdir('wfm'))}"


for name, fn in [
    ("s3 sources bucket", s3_sources),
    ("restricted parameters", restricted_parameters_are_hidden),
    ("activity api", activity_api),
    ("postgres (psycopg)", postgres),
    ("postgres (spark jdbc)", postgres_jdbc),
    ("sftp", sftp),
]:
    check(name, fn)

for name, outcome in results.items():
    print(f"{name:<24} {outcome}")

# COMMAND ----------

dbutils.notebook.exit(json.dumps(results))
