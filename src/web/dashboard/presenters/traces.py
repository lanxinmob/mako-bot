from __future__ import annotations

from src.models.schemas import ThoughtTrace


def _format_traces(traces: list[ThoughtTrace]) -> list[dict]:
    return [_format_trace_record(trace) for trace in traces]



def _format_trace_record(trace: ThoughtTrace) -> dict:
    payload = trace.payload or {}
    trace_type = trace.trace_type or trace.trace_kind
    input_summary = trace.input_summary or _payload_input_summary(trace, payload)
    context_summary = trace.context_summary or _payload_context_summary(trace, payload)
    retrieved_summary = trace.retrieved_summary or _payload_retrieved_summary(trace, payload)
    decision_summary = trace.decision_summary or _payload_decision_summary(trace, payload)
    output_summary = trace.output_summary or _payload_output_summary(trace, payload)
    safety_notes = trace.safety_notes or "仅展示可审计摘要，不展示也不保存隐藏推理链。"
    target_label = _trace_target_label(trace, payload)
    summary = _format_trace(trace)
    title = _trace_title(trace.source, trace_type)
    return {
        "id": trace.trace_id,
        "trace_id": trace.trace_id,
        "title": title,
        "source": trace.source,
        "trace_type": trace_type,
        "type": trace_type,
        "summary": summary,
        "body": summary,
        "input_summary": input_summary,
        "context_summary": context_summary,
        "retrieved_summary": retrieved_summary,
        "decision_summary": decision_summary,
        "output_summary": output_summary,
        "safety_notes": safety_notes,
        "trigger_source": _trigger_source_label(trace, payload, input_summary),
        "context_observed": context_summary,
        "retrieved_memory": _split_summary(retrieved_summary),
        "decision_result": decision_summary,
        "final_output": output_summary,
        "audit_note": "这里是审计摘要：记录输入/上下文/检索/决策/输出的可复核结论，不记录隐藏推理链。",
        "target_label": target_label,
        "tags": [item for item in [trace.source, trace_type, target_label] if item],
        "user_id": trace.user_id,
        "group_id": trace.group_id,
        "payload": _safe_trace_payload(payload),
        "created_at": trace.created_at.isoformat(),
    }



def _trace_title(source: str, trace_type: str) -> str:
    labels = {
        "chat_reply_generated": "聊天回复生成",
        "decision_made": "自主行动决策",
        "note_write_summary": "笔记写入摘要",
        "note_update_summary": "笔记更新摘要",
        "relationship_extraction": "关系记忆抽取",
    }
    return labels.get(trace_type, trace_type or source or "思考摘要")



def _trigger_source_label(trace: ThoughtTrace, payload: dict, input_summary: str) -> str:
    parts = []
    if trace.source:
        parts.append(trace.source)
    if trace.trace_type or trace.trace_kind:
        parts.append(trace.trace_type or trace.trace_kind)
    if trace.user_id:
        parts.append(f"用户 {trace.user_id}")
    if trace.group_id:
        parts.append(f"群 {trace.group_id}")
    suggestion = payload.get("suggestion_preview")
    if suggestion:
        parts.append(f"owner 建议：{suggestion}")
    elif input_summary:
        parts.append(input_summary)
    return " / ".join(str(part) for part in parts if part)



def _trace_target_label(trace: ThoughtTrace, payload: dict) -> str:
    target_type = payload.get("target_type")
    target_id = payload.get("target_id")
    if target_type and target_id:
        label = "群聊" if target_type == "group" else "私聊" if target_type == "private" else "目标"
        return f"{label} {target_id}"
    if trace.group_id:
        return f"群聊 {trace.group_id}"
    if trace.user_id:
        return f"用户 {trace.user_id}"
    return ""



def _payload_input_summary(trace: ThoughtTrace, payload: dict) -> str:
    for key in ["input_preview", "suggestion_preview", "text_preview", "content_preview", "title"]:
        value = payload.get(key)
        if value:
            return str(value)
    return trace.summary or "旧记录未保存触发输入摘要。"



def _payload_context_summary(trace: ThoughtTrace, payload: dict) -> str:
    if trace.source == "autonomy":
        target_hint = payload.get("target_hint")
        recent_count = payload.get("recent_record_count")
        context_preview = payload.get("context_preview")
        return (
            f"读取 {recent_count if recent_count is not None else '若干'} 条近期记录；"
            f"目标解析提示：{target_hint or '旧记录未保存'}；"
            f"上下文预览：{context_preview or '旧记录未保存'}"
        )
    if trace.source == "chat":
        return (
            "普通聊天回复会结合当前消息、历史上下文、用户档案/关系记忆和茉子人格提示。"
            f" 历史轮数：{payload.get('history_turns', '旧记录未保存')}。"
        )
    if trace.source == "notes":
        return "笔记事件来自 owner 或聊天触发的记忆沉淀，并同步到笔记存储与向量索引。"
    if trace.source == "relationship":
        return str(payload.get("text_preview") or "关系记忆抽取来自用户消息中的偏好、禁忌、事件或承诺。")
    return "旧记录未保存上下文摘要。"



def _payload_retrieved_summary(trace: ThoughtTrace, payload: dict) -> str:
    if trace.source == "autonomy":
        return (
            "近期 all_memory、群/私聊白名单、动态白名单、冷却状态、GovernanceService 限制。"
            f" 群白名单={payload.get('allowed_groups') or '旧记录未保存'}；"
            f"私聊白名单={payload.get('allowed_private_users') or '旧记录未保存'}。"
        )
    if trace.source == "chat":
        return (
            f"用户画像摘要：{payload.get('profile_preview') or '旧记录未保存'}；"
            f"知识/记忆检索摘要：{payload.get('knowledge_preview') or '旧记录未保存'}。"
        )
    if trace.source == "notes":
        return "写入 notes:* 后可被 list_all_notes 和向量索引读取。"
    if trace.source == "relationship":
        memories = payload.get("memories")
        if isinstance(memories, list) and memories:
            return "；".join(
                str(item.get("content_preview") or item.get("memory_type") or item)
                for item in memories
                if isinstance(item, dict)
            )
        types = payload.get("memory_types")
        if types:
            return f"抽取类型：{types}"
    return "旧记录未保存检索记忆摘要。"



def _payload_decision_summary(trace: ThoughtTrace, payload: dict) -> str:
    if trace.source == "autonomy" or trace.trace_type == "decision_made":
        return (
            f"action={payload.get('action', 'unknown')}；"
            f"target={payload.get('target_type', 'none')}:{payload.get('target_id', 'none')}；"
            f"confidence={payload.get('confidence', 'unknown')}；"
            f"risk={payload.get('risk', 'unknown')}；"
            f"reason={payload.get('reason', '未保存原因')}"
        )
    if trace.source == "chat":
        return f"生成普通聊天回复；模型={payload.get('model', 'unknown')}；没有把隐藏推理链写入记录。"
    if trace.source == "notes":
        return "将笔记变更沉淀为可检索记忆，不产生主动发言。"
    if trace.source == "relationship":
        return f"抽取并保存 {payload.get('memory_count', 0)} 条关系记忆，同步用户档案。"
    return "旧记录未保存结构化决策摘要。"



def _payload_output_summary(trace: ThoughtTrace, payload: dict) -> str:
    for key in ["reply_preview", "message_preview", "content_preview"]:
        value = payload.get(key)
        if value:
            return str(value)
    if trace.source == "notes":
        title = payload.get("title")
        return f"笔记已更新：{title}" if title else "笔记已更新。"
    if trace.source == "relationship":
        return "关系记忆已写入存储、用户档案和笔记索引。"
    return "旧记录未保存最终输出摘要。"



def _safe_trace_payload(payload: dict) -> dict:
    blocked_keys = {"api_key", "token", "authorization", "password", "secret", "prompt", "messages"}
    safe = {}
    for key, value in payload.items():
        lowered = str(key).lower()
        if any(blocked in lowered for blocked in blocked_keys):
            safe[key] = "[redacted]"
        else:
            safe[key] = value
    return safe



def _split_summary(value: str) -> list[str]:
    if not value:
        return []
    parts = []
    for chunk in str(value).replace("\n", "；").split("；"):
        chunk = chunk.strip(" -:：")
        if chunk:
            parts.append(chunk)
    return parts[:8]



def _format_trace(trace: ThoughtTrace) -> str:
    pieces = [
        trace.summary,
        trace.context_summary,
        trace.retrieved_summary,
        trace.decision_summary,
        trace.output_summary,
        trace.safety_notes,
    ]
    return "\n".join(piece for piece in pieces if piece).strip()
