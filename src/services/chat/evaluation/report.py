"""Evidence, fixed denominators and comparable report output."""
import hashlib
import json
import platform
import subprocess
from pathlib import Path

from .schema import KINDS


def summarize(rows):
    metrics = {}
    for kind in sorted(KINDS):
        n = sum(r["metrics"][kind]["numerator"] for r in rows)
        d = sum(r["metrics"][kind]["denominator"] for r in rows)
        metrics[kind] = dict(numerator=n, denominator=d, rate=n / d if d else None)
    return dict(total=len(rows), passed=sum(r["passed"] for r in rows),
                completed=sum(r["completed"] for r in rows), metrics=metrics,
                duplicate_sends=sum(r["duplicate_sends"] for r in rows))


def metadata(root, dataset_sha, *, git_root=None):
    from src.services.chat.group.service import GroupConversationService
    from src.services.delivery.dispatcher import OutboundDispatcher
    service = GroupConversationService(bot_user_id="9001")
    dispatcher = OutboundDispatcher()
    files = sorted({*root.glob("src/services/chat/group/*.py"),
                    *root.glob("src/services/chat/pipeline/*.py"),
                    root / "src/services/chat/policy.py", root / "src/services/chat/rhythm.py",
                    root / "src/plugins/chat/delivery.py", root / "src/services/delivery/dispatcher.py"})
    sources = {str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in files}
    version = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(
        (root / "src/services/chat/evaluation").glob("*.py")))).hexdigest()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_root or root, capture_output=True,
                          text=True, check=True).stdout.strip()
    return dict(git_head=head, sources=sources, dataset_sha256=dataset_sha, python=platform.python_version(),
                replay_contract=1, replay_version=version,
                parameters=dict(debounce=service.debounce_seconds, max_wait=service.max_wait_seconds,
                                lease=service.lease_seconds, candidate_ttl=service.candidate_ttl_seconds,
                                window_ttl=service.window.ttl_seconds, max_events=service.window.max_events,
                                natural_delay_sample=.5, dispatcher_spacing=dispatcher.spacing,
                                dispatcher_chat_wait=dispatcher.chat_wait,
                                rhythm={k: __import__('src.core.config', fromlist=['Settings']).Settings.model_fields[k].default
                                        for k in ('chat_rhythm_enabled', 'chat_rhythm_fast_turn_seconds',
                                                  'chat_rhythm_window_seconds', 'chat_rhythm_cooldown_seconds')}))


def build(rows, meta):
    hard = [r for r in rows if r["hard"]]
    overall, strict = summarize(rows), summarize(hard)
    accepted = (overall["completed"] == 40 and strict["passed"] == 35
                and overall["passed"] >= 36 and not overall["duplicate_sends"]
                and all(v["numerator"] == 0 for v in strict["metrics"].values()))
    return dict(source="replay", metadata=meta, summary=overall, hard_summary=strict,
                splits={s: summarize([r for r in rows if r["split"] == s]) for s in ("dev", "holdout")},
                accepted=accepted, cases=rows)


def compare(current, baseline):
    for field in ("dataset_sha256", "parameters", "replay_contract", "replay_version"):
        if current["metadata"][field] != baseline["metadata"][field]:
            raise ValueError("comparison incompatible: " + field)
    return {k: {"before": baseline["summary"]["metrics"][k], "after": v}
            for k, v in current["summary"]["metrics"].items()}


def write(report, out, comparison=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = report["summary"]
    lines = ["# 群聊节奏回放", "", "仅为合成回放，不证明模型正文质量、真实 QQ 送达或线上打扰下降。",
             "", f"通过 {summary['passed']}/{summary['total']}；完成 {summary['completed']}/40。",
             f"硬场景 {report['hard_summary']['passed']}/35；验收：{'通过' if report['accepted'] else '未通过'}。",
             "", "| 指标 | 分子 / 分母 |", "| --- | --- |"]
    for key, value in summary["metrics"].items():
        lines.append(f"| {key} | {value['numerator']} / {value['denominator']} |")
    if comparison:
        lines.extend(["", "## 相同样例前后比较", ""])
        for key, value in comparison.items():
            a, b = value["before"], value["after"]
            lines.append(f"- {key}: {a['numerator']}/{a['denominator']} → {b['numerator']}/{b['denominator']}")
    lines.extend(["", "## 逐例证据", ""])
    for row in report["cases"]:
        lines.append(f"- {row['case_id']} ({row['split']}): {'通过' if row['passed'] else '失败'}")
        lines.extend("  - " + error for error in row["errors"])
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
