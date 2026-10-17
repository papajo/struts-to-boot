#!/usr/bin/env python3
"""Find which seeded table(s) break login, by bisection. Unattended; ~15-20 min.

  python3 legacy/bisect-seed.py            # starts from a fresh DB (docker compose down -v)

Each round: restore the pre-seed dump, apply the seed blocks for a subset of tables,
restart Mifos, run legacy/login-check.sh. Prints the culprit table(s) at the end and
leaves the DB in the pre-seed state.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DC = ["docker", "compose", "-f", str(ROOT / "legacy/docker-compose.yml")]
MYSQL = ["mysql", "-h127.0.0.1", "-P3306", "-umifos", "-pmifos", "--protocol=TCP", "mifos"]
CACHE = ROOT / "legacy/.cache"
PRESEED = CACHE / "preseed.sql"
SEED = CACHE / "bisect-seed.sql"
DSN = "mysql://mifos:mifos@127.0.0.1:3306/mifos"
DATASET = ROOT / "legacy-src/acceptanceTests/src/test/resources/dataSets/acceptance_dbunit.xml"


def sh(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def port() -> str:
    env = ROOT / "legacy/.env"
    for line in (env.read_text().splitlines() if env.exists() else []):
        if line.startswith("MIFOS_PORT="):
            return line.split("=", 1)[1].strip()
    return "18080"


def wait_up(timeout=420):
    url = f"http://localhost:{port()}/mifos/login.ftl"
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if urllib.request.urlopen(url, timeout=5).status == 200:
                return
        except Exception:
            pass
        time.sleep(5)
    raise SystemExit("Mifos did not come up")


def login_ok() -> bool:
    r = subprocess.run([str(ROOT / "legacy/login-check.sh")], capture_output=True, text=True)
    print("      ", r.stdout.strip())
    return r.returncode == 0


def restart_mifos():
    sh(DC + ["restart", "mifos"], capture_output=True)
    wait_up()


def mysql_file(path: Path):
    with path.open("rb") as f:
        sh(MYSQL, stdin=f, capture_output=True)


def blocks(seed_sql: str):
    """header, {table: [stmts]}, footer"""
    header, footer, per = [], [], {}
    for line in seed_sql.splitlines():
        m = re.match(r"(?:DELETE FROM|INSERT(?: IGNORE)? INTO) `([^`]+)`", line)
        if m:
            per.setdefault(m[1], []).append(line)
        elif per:
            footer.append(line)
        else:
            header.append(line)
    return header, per, footer


def apply(tables, header, per, footer):
    # Mifos must be down: its pooled connections hold metadata locks, so the dump's
    # DROP TABLEs would wait forever ("Waiting for table metadata lock").
    sh(DC + ["stop", "mifos"], capture_output=True)
    mysql_file(PRESEED)
    sql = "\n".join(header + [s for t in tables for s in per[t]] + footer)
    tmp = CACHE / "bisect-subset.sql"
    tmp.write_text(sql)
    mysql_file(tmp)
    sh(DC + ["start", "mifos"], capture_output=True)
    wait_up()


def fails(tables, header, per, footer) -> bool:
    print(f"  testing {len(tables)} table(s): {', '.join(tables[:6])}{' …' if len(tables) > 6 else ''}")
    apply(tables, header, per, footer)
    return not login_ok()


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    print("fresh DB …")
    sh(DC + ["down", "-v"], capture_output=True)
    sh(DC + ["up", "-d"], capture_output=True)
    wait_up()
    if not login_ok():
        raise SystemExit("login fails on a fresh DB — not a seed problem")
    with PRESEED.open("w") as f:
        sh(["mysqldump", "-h127.0.0.1", "-P3306", "-umifos", "-pmifos", "--protocol=TCP",
            "--lock-tables", "--no-tablespaces", "--hex-blob", "mifos"], stdout=f, stderr=subprocess.DEVNULL)
    py = ROOT / "harness/.venv/bin/python"
    sh([str(py), str(ROOT / "tools/dbunit2sql.py"), str(DATASET), "--dsn", DSN, "-o", str(SEED),
        "--report", str(CACHE / "bisect-report.md")], capture_output=True)
    header, per, footer = blocks(SEED.read_text())
    tables = list(per)
    print(f"{len(tables)} seeded tables")
    if not fails(tables, header, per, footer):
        sh(DC + ["stop", "mifos"], capture_output=True); mysql_file(PRESEED)
        sh(DC + ["start", "mifos"], capture_output=True)
        raise SystemExit("full seed did NOT break login this time — flaky; rerun")
    while len(tables) > 1:
        half = tables[: len(tables) // 2]
        rest = tables[len(tables) // 2:]
        if fails(half, header, per, footer):
            tables = half
        elif fails(rest, header, per, footer):
            tables = rest
        else:
            print(f"\nneither half alone breaks login: interaction among {len(tables)} tables:")
            print("  " + ", ".join(tables))
            break
    else:
        t = tables[0]
        print(f"\nCULPRIT: `{t}`  ({len(per[t])} statements)")
        for s in per[t][:5]:
            print("  " + s[:200])
    sh(DC + ["stop", "mifos"], capture_output=True)
    mysql_file(PRESEED)
    sh(DC + ["start", "mifos"], capture_output=True)
    wait_up()
    print("DB back to pre-seed state.")


if __name__ == "__main__":
    sys.exit(main())
