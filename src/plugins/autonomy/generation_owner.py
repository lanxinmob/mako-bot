"""Format the Owner's generation evidence without exposing stored content."""
from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable
from src.services.persistence.generation.review import inspect_generation, list_generations


_STATES = {"calling": "调用已登记，结果未确认", "unknown": "结果未知，待核对",
           "completed": "生成已完成", "missing": "没有记录", "invalid": "记录损坏或版本不支持，待核对"}
_COSTS = {"not_ready": "金额未确认", "needs_review": "待核对", "pending": "待补记",
          "retry_wait": "等待重试", "leased": "补记处理中", "complete": "已完成"}
_PHASES = {"reply": "主回复", "fact_check": "事实校验"}


def format_generation(entry):
    text = f"{entry.attempt_id}：{_STATES[entry.state]}"
    if entry.phase:
        text += f"；{_PHASES[entry.phase]}；费用归属日={entry.cost_day}；费用={_COSTS[entry.cost_state]}"
    if entry.amount is not None:
        text += f"；估算金额={entry.amount:.8g}（非供应商账单）"
    return text


def generation_feedback(client, operation, argument):
    try:
        if operation == "generation_inspect":
            text = format_generation(inspect_generation(client, argument))
        else:
            page = list_generations(client, argument)
            text = "生成记录（本页）：\n" + ("\n".join(map(format_generation, page.entries)) or "本页没有记录。")
            text += (f"\n继续：生成列表 {page.next_cursor}" if page.next_cursor else "\n本轮扫描结束。")
            text += "\n列表不是固定快照。"
        return text + "\n未确认不等于未调用或未计费；查询不触发模型调用或补费。"
    except EffectUnavailable:
        return "生成记录暂不可用，未触发模型调用或补费。"
    except (EffectNeedsReview, ValueError):
        return "生成记录需人工核对，未触发模型调用或补费。"
