"""Read-only, payload-free Owner view of validated post-delivery tasks."""
from src.services.delivery.effects.store import EffectStore
from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable


_KINDS = {
    "followup_complete": "跟进源完成", "reminder_complete": "提醒源完成",
    "outbound_dedup": "出站去重", "global_history": "全局历史",
    "news_fingerprints": "资讯指纹",
}
_STATES = {
    "pending": "待处理", "leased": "处理中", "retry_wait": "等待重试",
    "complete": "已完成", "skipped": "已跳过", "needs_review": "待核对",
}
_REASONS = {
    "actual_delivery_time_unknown": "实际送达时间未知",
    "superseded": "源版本已更新", "cancelled": "源任务已取消",
    "missing": "缺少源记录", "inconsistent": "源记录不一致",
    "wrong_action": "动作绑定不一致", "conflict": "补记回执冲突",
    "execution_error": "执行异常", "invalid_payload": "补记数据或执行结果需核对",
    "target_incomplete": "目标可能已部分写入，禁止自动重试",
    "unavailable": "存储暂不可用",
}


def effect_feedback(client, action_id):
    """Never claim/retry effects or echo stored payloads and error strings."""
    try:
        snapshot = EffectStore(client).inspect(action_id)
    except EffectUnavailable:
        return "\n补记状态暂不可用；不影响上方已读到的发送状态。"
    except EffectNeedsReview:
        return "\n补记待核对：旧记录缺少可验证计划，或任务数据不完整；不能据此判断已完成，也未触发补记。"
    if snapshot is None:
        return "\n未读到可展示的已送达补记记录；请稍后重新查询。"
    lines = ["补记任务（查询快照）："]
    for task in snapshot.tasks:
        label = _KINDS.get(task.kind, "补记任务")
        state = _STATES[task.state]
        reason = ("实际送达时间未知" if task.time_basis == "unknown"
                  else _REASONS.get(task.result_code, ""))
        suffix = f"（{reason}）" if reason else ""
        lines.append(f"{label}：{state}{suffix}；尝试次数={task.attempts}")
    lines.append("查询不会重发消息或触发补记。")
    return "\n" + "\n".join(lines)
