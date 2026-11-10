"""Command line entry point: generate every source's data into a local folder.

    python -m data_generator.simulate --out output              # 90 days, full volume
    python -m data_generator.simulate --out output --scale 0.1 --days 14

The output folder mirrors the four source systems, each as it looks at ``--as-of``
(by default the end of the last simulated day):

    output/casedesk/        one CSV per CaseDesk table
    output/activity_api/    segments.jsonl, as the activity tracker API returns them
    output/s3/              HR roster snapshots and QC result exports
    output/sftp/wfm/        forecasts, schedules and remediation plans
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .config import GeneratorConfig
from .master import build_master
from .simulation import simulate
from .sources.activity_api import write_activity_api
from .sources.casedesk import write_casedesk
from .sources.s3_drops import write_qc_results, write_roster
from .sources.wfm_sftp import write_wfm_files


def end_of(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=UTC)


def generate(cfg: GeneratorConfig, out_dir: Path, as_of: datetime | None = None) -> dict:
    as_of = as_of or end_of(cfg.end_date)
    md = build_master(cfg)
    sim = simulate(cfg, md)
    counts = {}
    counts |= write_casedesk(md, sim, out_dir, as_of)
    counts |= write_activity_api(md, sim, out_dir, as_of)
    counts |= write_roster(md, out_dir, as_of, first=cfg.start_date)
    counts |= write_qc_results(md, sim, out_dir, as_of)
    counts |= write_wfm_files(md, out_dir, as_of)
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "config": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in asdict(cfg).items()},
        "counts": counts,
    }
    (out_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate SupportHub source data.")
    parser.add_argument("--out", type=Path, default=Path("output"), help="output folder (replaced)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start-date", type=date.fromisoformat, default=GeneratorConfig.start_date)
    parser.add_argument("--days", type=int, default=GeneratorConfig.days)
    parser.add_argument("--scale", type=float, default=1.0, help="multiply staff and volumes, e.g. 0.1")
    args = parser.parse_args(argv)

    cfg = GeneratorConfig(seed=args.seed, start_date=args.start_date, days=args.days)
    if args.scale != 1.0:
        cfg = cfg.scaled(args.scale)
    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)

    started = time.perf_counter()
    manifest = generate(cfg, args.out)
    print(
        f"Generated {cfg.days} days ({cfg.start_date} to {cfg.end_date}) into {args.out}/ "
        f"in {time.perf_counter() - started:.0f}s"
    )
    for name, n in manifest["counts"].items():
        print(f"  {name:<26} {n:>10,}")


if __name__ == "__main__":
    main()
