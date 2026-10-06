"""History evidence and conservative reconciliation behind the Owner gate."""
from src.services.chat.history_delivery.review import inspect_history, list_histories
from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable
from src.services.persistence.history_commit.reconciliation import HistoryReconciliation


_STATES = {"prepared": "计划已保存，尚未开始传输", "sending": "传输已登记，结果未确认",
           "unknown": "送达未知，待核对", "sent": "送达已确认", "rejected": "未进入传输已终结",
           "abandoned": "人工放弃后续处理，不代表未送达",
           "missing": "没有记录", "invalid": "记录需人工核对"}
_TASKS = {"dormant": "未激活", "pending": "待补记", "leased": "补记处理中",
          "retry_wait": "等待重试", "complete": "已完成", "needs_review": "待核对"}
_REASONS = {"history_conflict": "会话基线已改变，保留新历史", "conflict": "效果身份冲突",
            "target_incomplete": "目标可能部分写入", "invalid_payload": "冻结载荷需核对",
            "execution_error": "执行结果需核对", "unavailable": "存储结果未确认",
            "time_unconfirmed": "实际送达时间未知，不使用核对时间补记"}


def format_history(entry):
    text = f"{entry.action_id}：{_STATES[entry.state]}"
    if entry.state == "sent" and entry.confirmation_source == "owner":
        text = f"{entry.action_id}：人工核对已送达，实际送达时间未知"
    if entry.target:
        text += f"；bot={entry.bot_id}；目标={entry.target}"
    for kind, state, attempts, result in entry.tasks:
        label = "会话历史" if kind == "session" else "全局历史"
        text += f"\n{label}={_TASKS[state]}；尝试={attempts}"
        if result in _REASONS:
            text += "；" + _REASONS[result]
    return text


def history_feedback(client, operation, argument, operator_id=None):
    try:
        if operation == "history_inspect":
            text = format_history(inspect_history(client, argument))
        elif operation == "history_list":
            page = list_histories(client, argument)
            text = "聊天历史记录（本页）：\n" + ("\n".join(map(format_history, page.entries)) or "本页没有记录。")
            text += (f"\n继续：聊天历史列表 {page.next_cursor}" if page.next_cursor else "\n本轮扫描结束。")
            text += "\n列表不是固定快照。"
        elif operation in {"history_sent", "history_abandoned"}:
            result = HistoryReconciliation(client).reconcile(
                argument, delivered=operation == "history_sent", operator_id=operator_id)
            if result in {"sent", "abandoned"}:
                text = "人工核对已保存。\n" + format_history(inspect_history(client, argument))
            else:
                text = "本次人工核对未更改记录；仅送达未知状态可核对。\n" + format_history(inspect_history(client, argument))
            return text + "\n未触发补记、重发或模型调用。"
        else:
            raise ValueError("invalid history owner operation")
        return text + "\n查询不触发补记、重发或模型调用；送达确认与历史补齐分别记录。"
    except EffectUnavailable:
        return "聊天历史记录暂不可用，本次核对结果未确认；未触发补记或重发。"
    except (EffectNeedsReview, ValueError):
        return "聊天历史记录需人工核对，未触发补记或重发。"
