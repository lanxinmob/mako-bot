from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from src.models.schemas import ThoughtTrace


from src.services.persistence.backends import Repository
from src.services.persistence.autonomy import normalization


class TracesRepository(Repository):
    def save_thought_trace(self, trace: ThoughtTrace) -> ThoughtTrace:
        payload = json.dumps(trace.model_dump(mode="json"), ensure_ascii=False)
        if self.redis:
            self.redis.hset("thought_traces", trace.trace_id, payload)
            return trace
        self.backend.memory.thought_traces[trace.trace_id] = trace.model_dump(mode="json")
        return trace

    def add_thought_trace(
        self,
        summary: str,
        *,
        trace_kind: str = "chat",
        source: str = "",
        trace_type: str = "",
        input_summary: str = "",
        context_summary: str = "",
        retrieved_summary: str = "",
        decision_summary: str = "",
        output_summary: str = "",
        safety_notes: str = "",
        payload: Optional[dict] = None,
        user_id: Optional[int] = None,
        group_id: Optional[int] = None,
        session_id: Optional[str] = None,
        related_goal_id: Optional[str] = None,
        related_task_id: Optional[str] = None,
    ) -> ThoughtTrace:
        trace = ThoughtTrace(
            trace_id=uuid.uuid4().hex[:12],
            trace_kind=normalization.normalize_trace_kind(trace_kind),  # type: ignore[arg-type]
            source=source,
            trace_type=trace_type,
            summary=summary,
            input_summary=input_summary,
            context_summary=context_summary,
            retrieved_summary=retrieved_summary,
            decision_summary=decision_summary,
            output_summary=output_summary,
            safety_notes=safety_notes,
            payload=payload or {},
            user_id=user_id,
            group_id=group_id,
            session_id=session_id,
            related_goal_id=related_goal_id,
            related_task_id=related_task_id,
        )
        return self.save_thought_trace(trace)

    def append_thought_trace(self, payload: dict) -> ThoughtTrace:
        created_at = normalization.parse_datetime(payload.get("created_at"))
        trace_kind = normalization.normalize_trace_kind(str(payload.get("trace_kind") or payload.get("trace_type") or "chat"))
        trace_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        derived = self._derive_trace_fields(
            source=str(payload.get("source") or ""),
            trace_type=str(payload.get("trace_type") or payload.get("event_type") or ""),
            summary=str(payload.get("summary") or ""),
            payload=trace_payload,
        )
        trace = ThoughtTrace(
            trace_id=str(payload.get("trace_id") or uuid.uuid4().hex[:12]),
            trace_kind=trace_kind,  # type: ignore[arg-type]
            source=str(payload.get("source") or ""),
            trace_type=str(payload.get("trace_type") or payload.get("event_type") or ""),
            summary=str(payload.get("summary") or ""),
            input_summary=str(payload.get("input_summary") or derived["input_summary"]),
            context_summary=str(payload.get("context_summary") or derived["context_summary"]),
            retrieved_summary=str(payload.get("retrieved_summary") or derived["retrieved_summary"]),
            decision_summary=str(payload.get("decision_summary") or derived["decision_summary"]),
            output_summary=str(payload.get("output_summary") or derived["output_summary"]),
            safety_notes=str(payload.get("safety_notes") or derived["safety_notes"]),
            payload=trace_payload,
            user_id=normalization.optional_int(payload.get("user_id") or trace_payload.get("user_id")),
            group_id=normalization.optional_int(payload.get("group_id") or trace_payload.get("group_id")),
            session_id=payload.get("session_id"),
            related_goal_id=payload.get("related_goal_id") or payload.get("goal_id"),
            related_task_id=payload.get("related_task_id") or payload.get("task_id"),
            created_at=created_at or datetime.now(),
        )
        return self.save_thought_trace(trace)

    @staticmethod
    def _derive_trace_fields(source: str, trace_type: str, summary: str, payload: dict) -> dict[str, str]:
        def value(key: str, default: str = "") -> str:
            item = payload.get(key, default)
            if item is None:
                return ""
            return str(item)

        source = source or "unknown"
        trace_type = trace_type or "trace"
        base_safety = "仅保存可审计摘要，不保存隐藏推理链。"

        if source == "autonomy" or "decision" in trace_type:
            target_type = value("target_type", "none")
            target_id = value("target_id", "none")
            confidence = value("confidence", "0")
            risk = value("risk", "unknown")
            reason = value("reason", "未提供原因")
            action = value("action", "unknown")
            message_preview = value("message_preview")
            context_preview = value("context_preview")
            target_hint = payload.get("target_hint")
            recent_count = value("recent_record_count", "0")
            return {
                "input_summary": value("suggestion_preview", "定时扫描或 owner 建议触发了一次自主行动判断。"),
                "context_summary": (
                    f"读取 {recent_count} 条近期记录；目标解析提示：{target_hint or '无'}；"
                    f"上下文预览：{context_preview or '未保存上下文预览'}"
                ),
                "retrieved_summary": (
                    "使用 AUTONOMY_GROUP_IDS、AUTONOMY_PRIVATE_USER_IDS、动态白名单、recent global records 和治理规则。"
                    f" 群白名单={payload.get('allowed_groups') or []}；私聊白名单={payload.get('allowed_private_users') or []}。"
                ),
                "decision_summary": (
                    f"action={action}; target={target_type}:{target_id}; "
                    f"confidence={confidence}; risk={risk}; reason={reason}"
                ),
                "output_summary": f"候选输出：{message_preview}" if message_preview else "本次没有形成可发送内容。",
                "safety_notes": (
                    f"{base_safety} 低风险高置信才直接行动；中风险/低置信先问 owner；高风险或疑似越界保持静默。"
                ),
            }

        if source == "chat":
            model = value("model", "unknown")
            return {
                "input_summary": value("input_preview", "收到一条聊天消息。"),
                "context_summary": (
                    f"结合当前会话上下文、用户画像/关系记忆和茉子人格提示生成普通回复；"
                    f"历史轮数={value('history_turns', 'unknown')}。"
                ),
                "retrieved_summary": (
                    f"用户画像摘要：{value('profile_preview', '未保存')}；"
                    f"知识/记忆检索摘要：{value('knowledge_preview', '未保存')}。"
                ),
                "decision_summary": f"生成普通聊天回复；模型={model}；没有触发自主行动发送决策。",
                "output_summary": value("reply_preview", "回复内容未写入摘要。"),
                "safety_notes": base_safety,
            }

        if source == "notes":
            title = value("title", "未命名笔记")
            category = value("category", "default")
            return {
                "input_summary": f"笔记变更：{title}",
                "context_summary": f"用户 {value('user_id', 'unknown')} 的笔记分类为 {category}。",
                "retrieved_summary": "写入 StorageService notes:*，并同步到向量索引用于后续检索。",
                "decision_summary": "这是记忆沉淀事件，不是主动发言决策。",
                "output_summary": value("content_preview", "笔记内容摘要未提供。"),
                "safety_notes": base_safety,
            }

        if source == "relationship":
            memory_count = value("memory_count", "0")
            memory_types = payload.get("memory_types")
            if not memory_types and isinstance(payload.get("memories"), list):
                memory_types = [item.get("memory_type") for item in payload["memories"] if isinstance(item, dict)]
            return {
                "input_summary": f"从用户 {value('user_id', 'unknown')} 的消息中抽取关系记忆。",
                "context_summary": value("text_preview", "关系抽取没有保存原文摘要。"),
                "retrieved_summary": f"抽取到 {memory_count} 条关系记忆；类型：{memory_types or '未标注'}。",
                "decision_summary": "将命中的偏好、禁忌、事件或承诺写入关系记忆与用户档案。",
                "output_summary": "关系记忆已同步到 StorageService、用户档案和笔记/向量索引。",
                "safety_notes": base_safety,
            }

        return {
            "input_summary": summary,
            "context_summary": "旧记录没有保存更细的上下文字段。",
            "retrieved_summary": "旧记录没有保存检索记忆摘要。",
            "decision_summary": "旧记录没有保存结构化决策字段。",
            "output_summary": "旧记录没有保存最终输出摘要。",
            "safety_notes": base_safety,
        }

    def get_thought_trace(self, trace_id: str) -> Optional[ThoughtTrace]:
        if self.redis:
            raw = self.redis.hget("thought_traces", trace_id)
            if not raw:
                return None
            try:
                return ThoughtTrace.model_validate_json(raw)
            except Exception:
                return None
        data = self.backend.memory.thought_traces.get(trace_id)
        return ThoughtTrace.model_validate(data) if data else None

    def list_thought_traces(
        self,
        *,
        trace_kind: Optional[str] = None,
        user_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[ThoughtTrace]:
        rows: List[str]
        if self.redis:
            rows = self.redis.hvals("thought_traces")
        else:
            rows = [json.dumps(item, ensure_ascii=False) for item in self.backend.memory.thought_traces.values()]
        traces: List[ThoughtTrace] = []
        for row in rows:
            try:
                trace = ThoughtTrace.model_validate_json(row)
            except Exception:
                continue
            if trace_kind and trace.trace_kind != trace_kind:
                continue
            if user_id is not None and trace.user_id != user_id:
                continue
            traces.append(trace)
        traces.sort(key=lambda x: x.created_at, reverse=True)
        return traces[:limit]
