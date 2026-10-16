"""harness record|replay|report

  harness record  --scenarios harness/scenarios --legacy http://localhost:8080/mifos [--legacy-db mysql://...]
  harness replay  --scenarios harness/scenarios --modern http://localhost:8081 [--modern-db mysql://...]
  harness report  --inventory docs/loan-inventory.json

Results land in harness/out/. `report` writes harness/out/REPORT.md with the
endpoint-match metric (endpoints whose every step matched / total inventory endpoints).
"""
import argparse
import json
import sys
from pathlib import Path

from .core import load_scenarios, record, replay

OUT = Path("harness/out")


def _scenarios(d: Path):
    return [sc for p in sorted(d.glob("*.yaml")) for sc in load_scenarios(p)]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--scenarios", type=Path, default=Path("harness/scenarios"))
    r.add_argument("--legacy", required=True)
    r.add_argument("--legacy-db")
    p = sub.add_parser("replay")
    p.add_argument("--scenarios", type=Path, default=Path("harness/scenarios"))
    p.add_argument("--modern", required=True)
    p.add_argument("--modern-db")
    rep = sub.add_parser("report")
    rep.add_argument("--inventory", type=Path, default=Path("docs/loan-inventory.json"))
    a = ap.parse_args(argv)

    if a.cmd == "record":
        for sc in _scenarios(a.scenarios):
            print("recorded", record(sc, a.legacy, OUT / "golden", a.legacy_db))
    elif a.cmd == "replay":
        allrows = {}
        for sc in _scenarios(a.scenarios):
            rows = replay(sc, a.modern, OUT / "golden", a.modern_db)
            allrows[sc.name] = rows
            for row in rows:
                print(("PASS " if row["match"] else "FAIL ") + f"{sc.name}/{row['step']}",
                      *row["diffs"], sep="\n    ")
        (OUT / "replay.json").write_text(json.dumps(allrows, indent=2))
        if not all(r["match"] for rows in allrows.values() for r in rows):
            sys.exit(1)
    elif a.cmd == "report":
        inv = json.loads(a.inventory.read_text())
        all_eps = {f"{x['path']}.do#{m}" for x in inv for m in x["methods"]}
        rows = [r for rs in json.loads((OUT / "replay.json").read_text()).values() for r in rs]
        by_ep: dict[str, bool] = {}
        for r in rows:
            by_ep[r["endpoint"]] = by_ep.get(r["endpoint"], True) and r["match"]
        matched = sorted(e for e, ok in by_ep.items() if ok)
        failed = sorted(e for e, ok in by_ep.items() if not ok)
        uncovered = sorted(all_eps - by_ep.keys())
        md = [
            "# Equivalence report", "",
            f"- Endpoints matched: **{len(matched)} / {len(all_eps)}**",
            f"- Failing: {len(failed)}", f"- Not yet covered by a scenario: {len(uncovered)}", "",
            "## Failing", *[f"- `{e}`" for e in failed], "",
            "## Uncovered", *[f"- `{e}`" for e in uncovered], "",
        ]
        (OUT / "REPORT.md").write_text("\n".join(md))
        print("\n".join(md[:5]))


if __name__ == "__main__":
    main()
