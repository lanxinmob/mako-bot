"""Synthetic-only CLI; run in a dedicated subprocess, never in the bot."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="eval/group_rhythm/cases.jsonl")
    parser.add_argument("--out", required=True)
    parser.add_argument("--compare")
    parser.add_argument("--split", choices=("dev", "holdout"))
    parser.add_argument("--source-root", help="verified baseline Python source snapshot")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if out == ROOT or ROOT in out.parents:
        parser.error("--out must be outside the repository")
    source_root = Path(args.source_root).resolve() if args.source_root else ROOT
    if args.source_root:
        sys.path.insert(0, str(source_root))
    # Windows needs its own loopback wakeup pipe before the external-network guard.
    loop = asyncio.new_event_loop()
    from src.services.chat.evaluation.isolation import install_read_guards
    install_read_guards()
    from src.services.chat.evaluation.schema import load_cases
    from src.services.chat.evaluation.report import metadata, build, compare, write
    from src.services.chat.evaluation.runner import replay
    from nonebot.log import logger
    logger.remove()
    cases, digest = load_cases(args.cases)
    selected = [c for c in cases if not args.split or c["split"] == args.split]
    try:
        rows = [loop.run_until_complete(replay(case)) for case in selected]
        report = build(rows, metadata(source_root, digest, git_root=ROOT))
        comparison = compare(report, json.loads(Path(args.compare).read_text(encoding="utf-8"))) if args.compare else None
        if comparison:
            report['comparison'] = comparison
            report['regressions'] = [key for key, value in comparison.items()
                                     if value['after']['numerator'] > value['before']['numerator']]
            if report['regressions']:
                report['accepted'] = False
        write(report, out, comparison)
        print(json.dumps({"out": str(out), "summary": report["summary"],
                          "accepted": report["accepted"]}, ensure_ascii=False))
        return 0 if (all(r["completed"] for r in rows) and (
            report["accepted"] if not args.split else all(r["passed"] for r in rows if r["hard"]))) else 1
    finally:
        loop.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
