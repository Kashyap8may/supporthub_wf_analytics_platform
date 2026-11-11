"""Databricks entry point for the daily source simulator (job: supporthub-source-simulator).

Puts the bundle's copy of the repo on the import path, hands boto3 the simulator IAM user's
key from the ``supporthub-dev`` secret scope, and runs ``data_generator.publish``. Every other
argument is passed through, e.g. ``--through 2026-11-10`` or ``--max-days 5``.
"""

import os
import sys

from databricks.sdk.runtime import dbutils

SCOPE = "supporthub-dev"


def main(argv: list[str]) -> int:
    repo_root = argv[argv.index("--repo-root") + 1]
    rest = [a for i, a in enumerate(argv) if a != "--repo-root" and (i == 0 or argv[i - 1] != "--repo-root")]
    if not repo_root.startswith("/Workspace"):
        repo_root = "/Workspace" + repo_root
    sys.path.insert(0, repo_root)

    os.environ["AWS_ACCESS_KEY_ID"] = dbutils.secrets.get(SCOPE, "aws_simulator_access_key_id")
    os.environ["AWS_SECRET_ACCESS_KEY"] = dbutils.secrets.get(SCOPE, "aws_simulator_secret_access_key")

    from data_generator.publish import main as publish

    return publish(rest)


if __name__ == "__main__":
    code = main(sys.argv[1:])
    if code:
        raise SystemExit(code)
