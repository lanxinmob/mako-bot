"""Validate frozen annotations before running any production code."""
import hashlib
import json
from pathlib import Path

CATEGORIES = ("明确呼叫", "旁观与对象识别", "结束与撤回回应需求", "等待和连续消息",
              "续接与隔离", "过期与并发", "显式工作与异常边界", "有歧义的日常表达")
KINDS = {"forbid_reply", "require_reply", "invalidated_candidate"}


def require(condition, case_id, reason):
    if not condition:
        raise ValueError(f"{case_id}: {reason}")


def validate(case):
    cid = case.get("case_id", "<missing>")
    for key in ("schema_version", "split", "hard", "category", "events", "checkpoints",
                "opportunities", "end_at_ms", "rationale"):
        require(key in case, cid, f"missing {key}")
    require(case["schema_version"] == 1, cid, "unsupported schema_version")
    require(case["split"] in {"dev", "holdout"}, cid, "invalid split")
    require(type(case["hard"]) is bool, cid, "hard must be boolean")
    require(case["category"] in CATEGORIES, cid, "unknown category")
    require(type(case["end_at_ms"]) is int and 0 <= case["end_at_ms"] <= 600000,
            cid, "invalid end_at_ms")
    seqs, targets = set(), set()
    previous = (-1, -1)
    for event in case["events"]:
        require(event.get("op") in {"inbound", "outbound_confirmed", "release_generation",
                                  "cancel_task"}, cid, "invalid event op")
        marker = (event.get("at_ms", -1), event.get("seq", -1))
        require(all(type(v) is int and v >= 0 for v in marker), cid, "time/seq must be nonnegative integers")
        require(marker >= previous, cid, "events not ordered")
        previous = marker
        require(0 <= marker[0] <= case["end_at_ms"], cid, "event outside observation period")
        require(marker[1] not in seqs, cid, "duplicate seq")
        seqs.add(marker[1])
        if event["op"] in {"inbound", "outbound_confirmed"}:
            for key in ("group", "message_id", "user", "text"):
                require(isinstance(event.get(key), str) and (event[key] or key == "text"),
                        cid, f"invalid event {key}")
            require("/" not in event["group"] + event["message_id"], cid, "slash in alias")
            quote = event.get("reply_to_message_id")
            require(not quote or (event["group"], quote) in targets
                    or event.get("unknown_quote", False), cid, "invalid quote reference")
            targets.add((event["group"], event["message_id"]))
    for point in case["checkpoints"]:
        require(point.get("action") in {"ignore", "wait", "reply", None}, cid, "invalid action")
        require(type(point.get('at_ms')) is int and type(point.get('seq')) is int,
                cid, "checkpoint time/seq must be integers")
        require(0 <= point.get("at_ms", -1) <= case["end_at_ms"], cid, "invalid checkpoint time")
        require(point.get("seq") not in seqs, cid, "duplicate checkpoint seq")
        seqs.add(point["seq"])
        target = point.get("target_message_id")
        require(target is None or (point["group"], target) in targets, cid, "unknown target")
        if point["action"] == "wait":
            bounds = point.get("wait_range_ms")
            require(isinstance(bounds, list) and len(bounds) == 2 and 0 <= bounds[0] <= bounds[1],
                    cid, "wait requires bounded interval")
    require(case["checkpoints"] and any("send_count" in p for p in case["checkpoints"]),
            cid, "missing terminal send count")
    ids, windows = set(), {}
    for op in case["opportunities"]:
        require(op.get("id") not in ids, cid, "duplicate opportunity")
        ids.add(op.get("id"))
        require(op.get("kind") in KINDS, cid, "invalid opportunity kind")
        require(all(type(op.get(f)) is int for f in ('start_ms', 'end_ms', 'allowed_send_count')),
                cid, "window/count must be integers")
        require(0 <= op["start_ms"] <= op["end_ms"] <= case["end_at_ms"], cid, "invalid window")
        require((op["group"], op["target_message_id"]) in targets, cid, "unknown opportunity target")
        require(type(op.get("normal_transport")) is bool, cid, "normal_transport must be boolean")
        for field in ("canceled_by", "replaced_by"):
            require(op.get(field) is None or op[field] in seqs, cid, f"unknown {field}")
        if op["kind"] == "invalidated_candidate":
            cause = op.get("invalidated_by")
            require(cause in seqs if isinstance(cause, int) else (
                isinstance(cause, dict) and cause.get("kind") == "candidate_ttl"
                and cause.get("at_ms") == op["start_ms"]), cid, "invalid invalidation cause")
            require("candidate_of" in op, cid, "missing candidate selector")
            ref = op['candidate_of']
            require(type(ref.get('ordinal')) is int and ref['ordinal'] >= 1
                    and (ref.get('group'), ref.get('message_id')) in targets,
                    cid, "invalid candidate selector")
        identity = (op['kind'], op['group'], '' if op['kind'] == 'forbid_reply' else op['target_message_id'])
        if op['kind'] == 'invalidated_candidate':
            identity += (op['candidate_of']['ordinal'],)
        for start, end in windows.get(identity, []):
            require(op['end_ms'] < start or op['start_ms'] > end, cid, "duplicate overlapping window")
        windows.setdefault(identity, []).append((op['start_ms'], op['end_ms']))
    for field in ("generation", "transport"):
        for key, config in case.get(field, {}).items():
            require(tuple(key.split("/")) in targets, cid, f"unknown {field} target")
            require(type(config.get("delay_ms", 10)) is int and config.get("delay_ms", 10) >= 0,
                    cid, "invalid dependency delay")
            if field == "transport":
                require(config.get("result", "ack") in {"ack", "unacknowledged", "explicit_failure"},
                        cid, "invalid transport result")


def eligible(op):
    return op["kind"] != "require_reply" or (
        op["normal_transport"] and op.get("canceled_by") is None and op.get("replaced_by") is None)


def load_cases(path):
    raw = Path(path).read_bytes()
    cases = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    require(len(cases) == 40, "dataset", "requires exactly 40 cases")
    require(len({c["case_id"] for c in cases}) == 40, "dataset", "duplicate case_id")
    for case in cases:
        validate(case)
    for category in CATEGORIES:
        rows = [c for c in cases if c["category"] == category]
        require(len(rows) == 5 and sum(c["split"] == "dev" for c in rows) == 3,
                "dataset", f"invalid quota for {category}")
        require(all(c["hard"] == (category != CATEGORIES[-1]) for c in rows),
                "dataset", "invalid hard allocation")
    for kind, minimum in zip(("forbid_reply", "require_reply", "invalidated_candidate"), (15, 15, 8)):
        count = sum(op["kind"] == kind and eligible(op) for c in cases for op in c["opportunities"])
        require(count >= minimum, "dataset", f"effective {kind} quota {count} < {minimum}")
        require(any(c["split"] == "holdout" and any(op["kind"] == kind and eligible(op)
                    for op in c["opportunities"]) for c in cases), "dataset", f"holdout lacks {kind}")
    digest = hashlib.sha256(raw).hexdigest()
    manifest = Path(path).with_name('frozen.json')
    if Path(path).name == 'cases.jsonl' and manifest.exists():
        require(json.loads(manifest.read_text(encoding='utf-8'))['sha256'] == digest,
                'dataset', 'frozen labels fingerprint mismatch')
    return cases, digest
