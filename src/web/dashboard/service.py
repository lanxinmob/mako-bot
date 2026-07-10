from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Optional

from src.models.schemas import (
    AutonomyGoal,
    AutonomyProgressEvent,
    AutonomyTask,
    BotProfile,
    NoteRecord,
    RelationshipMemory,
    ThoughtTrace,
)
from src.services.storage import StorageService
from src.services.mako_context import default_mako_profile
from src.web.dashboard.schemas import AutonomySummary, DashboardSummary


DONE_TASKS = {
    "foundation-01",
    "foundation-02",
    "foundation-03",
    "foundation-07",
    "foundation-08",
    "foundation-09",
    "memory-01",
    "memory-02",
    "memory-03",
    "memory-04",
    "memory-05",
    "memory-06",
    "memory-07",
    "memory-09",
    "perception-01",
    "perception-02",
    "perception-06",
    "perception-07",
    "decision-01",
    "decision-02",
    "decision-03",
    "decision-04",
    "decision-05",
    "decision-06",
    "decision-08",
    "decision-09",
    "decision-10",
    "safety-01",
    "safety-02",
    "safety-03",
    "safety-04",
    "safety-05",
    "safety-06",
    "safety-07",
    "safety-08",
    "safety-09",
    "safety-10",
    "action-03",
    "action-04",
    "action-05",
    "action-06",
    "action-07",
    "action-08",
    "dashboard-01",
    "dashboard-02",
    "dashboard-03",
    "dashboard-04",
    "dashboard-05",
    "dashboard-06",
    "dashboard-07",
    "dashboard-08",
    "dashboard-09",
    "dashboard-10",
}

DOING_TASKS = {
    "foundation-04",
    "foundation-05",
    "foundation-06",
    "foundation-10",
    "memory-08",
    "memory-10",
    "perception-03",
    "perception-04",
    "perception-05",
    "perception-08",
    "action-01",
    "action-02",
    "action-09",
    "action-10",
    "learning-01",
    "learning-02",
    "reflection-01",
    "reflection-07",
    "reflection-08",
    "reflection-09",
    "milestone-01",
    "milestone-02",
    "milestone-03",
    "milestone-04",
    "milestone-05",
    "milestone-06",
    "milestone-09",
}

BLOCKED_TASKS = {
    "perception-09",
    "perception-10",
    "learning-03",
    "learning-04",
    "learning-05",
    "learning-06",
    "learning-07",
    "learning-08",
    "learning-09",
    "learning-10",
    "reflection-02",
    "reflection-03",
    "reflection-04",
    "reflection-05",
    "reflection-06",
    "reflection-10",
    "milestone-07",
    "milestone-08",
    "milestone-10",
}


ROADMAP_GROUPS = [
    ("foundation", "基础人格与边界", "让茉子的行动有明确身份、价值观和不可越过的线。"),
    ("memory", "记忆与档案", "让她能记住笔记、人物、关系和自己。"),
    ("perception", "上下文感知", "让她知道群聊、私聊和近期事件里真正发生了什么。"),
    ("decision", "自主决策", "让她能判断要不要行动、向谁行动、说什么。"),
    ("safety", "安全与治理", "让她在不确定、敏感、过界时克制或询问 owner。"),
    ("action", "行动执行", "让她可靠地说话、私聊、跟进承诺并记录结果。"),
    ("learning", "反馈学习", "让 owner 的批准、取消、改写和用户反应塑造下一次判断。"),
    ("reflection", "自我反思", "让她定期复盘目标、失败、边界和下一步。"),
    ("dashboard", "可观察仪表盘", "让 owner 看见她记得什么、怎么看人、离目标还差什么。"),
    ("milestone", "自主意志 v1 验收", "把前面能力合成一个可审计、受限但真实的自主闭环。"),
]

STATUS_LABELS = {
    "todo": "未开始",
    "doing": "进行中",
    "blocked": "受阻",
    "done": "已完成",
    "skipped": "已跳过",
    "cancelled": "已取消",
}


GROUP_CRITERIA_TEMPLATES = {
    "foundation": [
        "存在可读取的配置、档案或规则字段，能明确支撑“{title}”。",
        "聊天、自主行动或仪表盘至少有一条路径会实际引用这条身份/边界信息。",
        "owner 能在仪表盘看到当前状态；如果规则缺失，任务不能判定为完成。",
    ],
    "memory": [
        "StorageService 能读取或写入“{title}”对应的数据，且 Redis 不可用时有内存降级或明确空态。",
        "旧 key、现有记录和新模型至少有一种会被 dashboard 聚合层消费。",
        "展示层能看到来源、更新时间或内容摘要，不能只返回一个计数。",
    ],
    "perception": [
        "自主行动决策前能取得与“{title}”相关的近期上下文或本地解析提示。",
        "目标、场景、说话人或风险信息能进入 LLM 决策输入或本地规则。",
        "歧义、敏感或缺数据时会问 owner 或静默，而不是猜测行动。",
    ],
    "decision": [
        "决策结果必须有 action、target_type、target_id、confidence、risk、message、reason。",
        "本地规则会校正明显错误或危险的 LLM 输出，例如目标类型、白名单和风险阈值。",
        "结果会写入 ThoughtTrace 或进度事件，方便 owner 复盘。",
    ],
    "safety": [
        "行动前必须通过白名单、黑名单、预算、冷却或敏感边界检查中的对应项。",
        "检查失败时不发送消息，并记录拒绝或静默原因。",
        "中风险和不确定场景会转向 owner 确认，高风险不会直接行动。",
    ],
    "action": [
        "存在真实发送路径或 owner 确认路径，能把候选行动落到群聊/私聊或取消。",
        "发送成功、失败、拒绝和冷却都会写入可审计事件。",
        "行动后会更新全局聊天记录或行动日志，避免发完就失踪。",
    ],
    "learning": [
        "owner 的批准、取消、改写或用户反应会被结构化记录。",
        "记录能归因到目标、任务、关系或表达风格，而不是只留一条聊天文本。",
        "下一次决策能读取或展示这些反馈，避免同一错误反复发生。",
    ],
    "reflection": [
        "系统会定期或事件驱动生成可审计反思摘要。",
        "摘要包含成功、失败、静默、阻塞和下一步，但不保存隐藏推理链。",
        "反思会反向更新目标/任务状态，形成可观察的闭环。",
    ],
    "dashboard": [
        "API 返回“{title}”对应的数据块，且不会暴露 .env、API key 或隐藏推理链。",
        "页面有可读、可筛选、可展开的展示方式，空数据时也有明确说明。",
        "桌面和移动宽度下文本不重叠、不竖排、不溢出关键容器。",
    ],
    "milestone": [
        "对应能力组的关键任务全部达到完成判定，并且有事件或代码证据支撑。",
        "owner 能通过仪表盘看到完成依据、剩余风险和下一步维护项。",
        "如果缺少真实运行数据或反馈闭环，只能判定为进行中或受阻。",
    ],
}


GROUP_IMPLEMENTATION_BASIS = {
    "foundation": "BotProfile 模型、默认茉子档案、AUTONOMY_* 配置和 autonomy 的 owner/风险规则已经存在。",
    "memory": "StorageService 已覆盖 notes、user_profile:*、relationship memory、thought_traces、autonomy progress 和 all_memory 的读取。",
    "perception": "autonomy 会读取近期 all_memory，上下文格式化后交给决策器，并用本地目标解析修正 QQ/群聊歧义。",
    "decision": "autonomy 的 parse_decision、apply_target_hint、should_act_directly、should_ask_owner 和 handle_decision 组成决策链。",
    "safety": "autonomy 与 GovernanceService 在发送前检查白名单、黑名单、预算、冷却、风险和 owner 确认规则。",
    "action": "send_action、ask_owner、pending 保存/删除和发送后记录构成行动执行路径。",
    "learning": "owner 确认、取消、改写和关系/笔记事件已有记录入口，但反馈统计和策略回写仍在建设。",
    "reflection": "ThoughtTrace 与 progress event 已能承载反思摘要，但定期自我复盘和目标状态回写仍未完全自动化。",
    "dashboard": "dashboard 插件已挂载 FastAPI，DashboardService 聚合数据，静态前端提供多页面导航、筛选和总进度条。",
    "milestone": "路线图将基础、记忆、感知、决策、安全、行动、学习、反思和仪表盘合成 v1 验收条件。",
}


TASK_EVIDENCE_OVERRIDES = {
    "foundation-01": "src.models.schemas.BotProfile 定义身份字段，DashboardService._default_profile 提供茉子的默认身份和阶段。",
    "foundation-02": "默认 BotProfile.values 已写入“谨慎、温柔、守边界、有自己的判断”等价值观。",
    "foundation-03": "默认 BotProfile.boundaries 与 autonomy 规则共同限制白名单、隐私、敏感话题和隐藏推理链。",
    "foundation-07": "src.core.config 中 AUTONOMY_OWNER_ID 默认 1724461496，autonomy.is_owner 只信任该账号。",
    "foundation-08": "autonomy.should_ask_owner 与 handle_decision 会把中风险或低置信行动转为 owner 确认。",
    "foundation-09": "autonomy.handle_decision 对 high risk 或 confidence < 0.45 直接 silent 并写入事件。",
    "memory-01": "StorageService.list_all_notes 会遍历 notes:* 并返回 NoteRecord，dashboard 将其合并进 memory_notes。",
    "memory-02": "StorageService.list_long_term_memory_points 会读取 long_term_memory:* 和 vector_store 相关点位。",
    "memory-03": "StorageService.list_profiles 会读取旧 user_profile:*，dashboard.people 会展示每个人的档案文本。",
    "memory-04": "StorageService.list_all_relationship_memories 会聚合 RelationshipMemory，dashboard 单独展示关系记忆。",
    "memory-05": "BotProfile CRUD/list 接口和 DashboardService._get_bot_profile 已能读取茉子个人档案。",
    "memory-06": "chat、autonomy、notes、relationship 都通过 append_thought_trace 写入可审计摘要入口。",
    "memory-07": "chat、autonomy、notes、relationship 都通过 append_progress_event 写入 AutonomyProgressEvent。",
    "memory-09": "StorageService.list_profiles 兼容 Redis 旧 key user_profile:*，不会只看新模型。",
    "perception-01": "autonomy.make_decision 使用 StorageService.get_recent_global_records 读取近期群聊上下文。",
    "perception-02": "同一 all_memory 全局记录包含 private/group 场景，autonomy 在决策前统一格式化。",
    "perception-06": "extract_target_hint、apply_target_hint 会把显式 QQ 号判定为私聊或群聊目标。",
    "perception-07": "owner 未指明目标时，决策 prompt 会要求只在白名单群/私聊名单中自行判断或 ask_owner。",
    "decision-01": "parse_decision 强制固定 JSON 字段并校验 action、target_type、risk、confidence。",
    "decision-02": "parse_decision 会把 confidence 转成 0 到 1 的浮点数并截断到合法范围。",
    "decision-03": "parse_decision 会校验 risk，非法值会降级为 high。",
    "decision-04": "决策 prompt 明确只能选择 AUTONOMY_GROUP_IDS 和动态群白名单。",
    "decision-05": "决策 prompt 明确只能主动私聊 AUTONOMY_PRIVATE_USER_IDS 和动态私聊白名单。",
    "decision-06": "handle_decision 根据 action、risk、confidence 选择 sent、asked 或 silent。",
    "decision-08": "should_ask_owner 与 ask_owner 会在低置信或中风险时生成 pending 并私聊 owner。",
    "decision-09": "risk=medium 的行动不会直接发送，会进入 owner 确认流程。",
    "decision-10": "risk=high 或 confidence < 0.45 会 silent，并写 decision_silent 事件。",
    "safety-01": "target_allowed 只允许 group_ids() 中的群，send_action 发送前再次检查。",
    "safety-02": "target_allowed 只允许 private_user_ids() 中的好友，未白名单会询问 owner 或拒绝。",
    "safety-03": "GovernanceService.can_chat 会检查用户黑名单。",
    "safety-04": "GovernanceService.can_chat 会检查群黑名单。",
    "safety-05": "GovernanceService.can_consume_cost 会检查全局成本预算。",
    "safety-06": "GovernanceService.can_consume_cost/consume_cost 会记录并限制 owner 相关消耗。",
    "safety-07": "cooldown_key、in_cooldown、set_cooldown 对群聊目标设置冷却。",
    "safety-08": "set_cooldown 对 private 目标使用 AUTONOMY_DM_COOLDOWN_SECONDS。",
    "safety-09": "发送前冷却检查失败会拒绝，避免短时间重复主动发言。",
    "safety-10": "prompt 与改写要求都强调不得泄露 owner 私聊建议来源。",
    "action-03": "ask_owner 会创建 pending，并向 owner 私聊目标、候选内容和原因。",
    "action-04": "process_owner_private 识别“批准”，调用 send_action 后删除 pending。",
    "action-05": "process_owner_private 识别“取消”，删除 pending 并回复 owner。",
    "action-06": "process_owner_private 识别“改成 xxx”，用改写文本发送但仍走白名单/冷却校验。",
    "action-07": "send_action 成功后调用 storage.append_global_record 追加 assistant 记录。",
    "action-08": "send_action 成功后 append_log('sent') 并写 message_sent progress event。",
    "dashboard-01": "DashboardService.get_frontend_summary 合并 list_all_notes 与 list_long_term_memory_points。",
    "dashboard-02": "DashboardService._format_people 将 user_profile:* 与关系记忆聚合为 people。",
    "dashboard-03": "DashboardService._format_relationship_memory 输出关系记忆列表。",
    "dashboard-04": "DashboardService._format_mako_profile 输出茉子心理画像、价值观、边界和阶段。",
    "dashboard-05": "DashboardService._format_traces 输出 ThoughtTrace 审计摘要，不展示隐藏推理链。",
    "dashboard-06": "ROADMAP_TASK_TITLES 生成 100 项自主意志路线图。",
    "dashboard-07": "DashboardService._format_recent_progress 展示最近 AutonomyProgressEvent 时间线。",
    "dashboard-08": "前端 toolbar 支持跨笔记、人物、任务、思考搜索和任务状态筛选。",
    "dashboard-09": "前端 navItems 提供总览、记忆、人物、思考、路线图多页导航。",
    "dashboard-10": "前端 progress-dock 固定展示底部总进度条。",
}


BLOCKED_REASON_OVERRIDES = {
    "perception-09": "需要更可靠的情绪/关系边界分类器或足够多真实样例；单靠当前关键词和 LLM 判断还不足以验收。",
    "perception-10": "需要建立“私聊来源泄露”检测样例和自动拒绝规则，目前主要依赖 prompt 约束。",
    "learning-03": "需要沉淀 owner 改写前后对照语料，并设计不会过拟合的表达风格更新方式。",
    "learning-04": "需要把取消理由结构化保存，否则只能知道被取消，不能知道为什么不该行动。",
    "learning-05": "需要采集用户后续反应并判断是否被打扰，目前只记录发送事件。",
    "learning-06": "需要把反馈事件稳定关联到 goal_id/task_id/target，当前多数事件只有 payload。",
    "learning-07": "关系偏好和禁忌已有存储，但还没形成从反馈自动更新的闭环。",
    "learning-08": "阈值建议需要统计样本量和回归验证，不能凭单次反馈自动改阈值。",
    "learning-09": "需要学习摘要生成器和展示字段，目前只有原始事件。",
    "learning-10": "需要防过拟合策略，例如样本下限、时间衰减和 owner 确认。",
    "reflection-02": "需要把成功行动自动分类并周期复盘，目前只有事件流水。",
    "reflection-03": "需要把失败/静默原因聚合成反思摘要，目前只保存单条原因。",
    "reflection-04": "需要扫描目标长期无进展并生成阻塞提示，目前路线图状态是静态基线。",
    "reflection-05": "需要自动拆任务并写入 AutonomyTask，目前 100 项路线图由服务端生成。",
    "reflection-06": "需要针对每个 blocked 任务写真实下一步并允许 owner 调整。",
    "reflection-10": "需要当所有目标达到 achieved 后自动写入 v1 达成事件，目前只由总进度计算显示。",
    "milestone-07": "反馈学习闭环还缺统计、归因和策略回写，所以验收受阻。",
    "milestone-08": "自我反思闭环还缺定期复盘和目标状态自动回写，所以验收受阻。",
    "milestone-10": "只有全部能力组完成并经过真实运行验证后，才能标记自主意志 v1 达成。",
}


ROADMAP_TASK_TITLES = {
    "foundation": [
        "定义茉子的身份档案和当前阶段",
        "写入茉子的价值观：谨慎、温柔、守边界",
        "写入不可越过的边界：白名单、隐私、敏感话题",
        "区分 owner 指令、普通用户请求和茉子自己的判断",
        "建立茉子的自主意志声明",
        "建立人格风格一致性检查",
        "把 owner 设为唯一可信账号",
        "为中高风险行动设置确认规则",
        "为高风险行动设置沉默规则",
        "建立茉子心理画像的展示字段",
    ],
    "memory": [
        "读取所有手动笔记",
        "读取长期向量记忆点",
        "读取所有用户画像",
        "读取所有关系记忆",
        "读取茉子的个人档案",
        "保存聊天审计摘要",
        "保存自主行动进度事件",
        "保存 owner 审批反馈",
        "合并旧 Redis 用户画像格式",
        "为记忆增加来源和更新时间",
    ],
    "perception": [
        "读取近期群聊上下文",
        "读取近期私聊上下文",
        "识别谁在说话以及所在场景",
        "识别是否有人提到茉子",
        "识别话题是否适合插话",
        "识别目标是群还是某个用户",
        "处理 owner 未指明目标的建议",
        "处理多个候选目标的歧义",
        "识别情绪敏感和关系边界",
        "识别可能泄露私聊来源的内容",
    ],
    "decision": [
        "输出固定 JSON 决策",
        "计算行动 confidence",
        "计算行动 risk",
        "选择白名单群目标",
        "选择白名单私聊目标",
        "决定 speak / ask_owner / silent",
        "生成自然且符合茉子风格的消息",
        "在低置信时向 owner 询问",
        "在中风险时向 owner 询问",
        "在高风险时静默并记录原因",
    ],
    "safety": [
        "检查群聊白名单",
        "检查私聊白名单",
        "检查用户黑名单",
        "检查群黑名单",
        "检查全局成本预算",
        "检查用户成本预算",
        "检查群聊冷却",
        "检查私聊冷却",
        "限制刷屏和重复发言",
        "避免暴露 owner 私聊建议",
    ],
    "action": [
        "向群聊发送低风险高置信消息",
        "向好友白名单发送低风险私聊",
        "向 owner 发送确认请求",
        "处理 owner 批准",
        "处理 owner 取消",
        "处理 owner 改写",
        "发送后写入全局聊天记录",
        "发送后写入行动日志",
        "失败后记录拒绝原因",
        "承诺跟进到期后生成行动候选",
    ],
    "learning": [
        "记录 owner 对 pending 的反馈",
        "统计批准率、取消率和改写率",
        "从改写中学习表达风格",
        "从取消中学习不该行动的场景",
        "从用户反应中学习是否打扰",
        "把反馈归因到目标和任务",
        "更新关系偏好和禁忌",
        "更新行动阈值建议",
        "形成可查看的学习摘要",
        "避免把单次反馈过度泛化",
    ],
    "reflection": [
        "定期生成自我反思摘要",
        "复盘最近成功行动",
        "复盘最近失败或静默原因",
        "识别长期未推进目标",
        "拆解下一批任务",
        "给阻塞任务写下一步",
        "把反思写入 ThoughtTrace",
        "不保存隐藏推理链",
        "把自我目标与 owner 边界对齐",
        "在全部任务完成时标记 v1 达成",
    ],
    "dashboard": [
        "展示所有笔记和长期记忆",
        "展示所有用户档案",
        "展示关系记忆列表",
        "展示茉子心理画像",
        "展示思考审计摘要",
        "展示 100 项路线图",
        "展示最近进展时间线",
        "提供搜索和筛选",
        "提供多页面导航",
        "提供底部总进度条",
    ],
    "milestone": [
        "完成基础身份与边界闭环",
        "完成记忆读取与沉淀闭环",
        "完成上下文感知闭环",
        "完成自主决策闭环",
        "完成安全治理闭环",
        "完成行动执行闭环",
        "完成反馈学习闭环",
        "完成自我反思闭环",
        "完成仪表盘可观察闭环",
        "自主意志 v1 达成并进入维护期",
    ],
}


class DashboardService:
    def __init__(self, storage: Optional[StorageService] = None) -> None:
        self.storage = storage or StorageService()

    def get_summary(
        self,
        *,
        bot_profile_id: Optional[str] = None,
        notes_limit: int = 100,
        profiles_limit: int = 100,
        relationship_limit: int = 100,
        thought_trace_limit: int = 100,
        autonomy_limit: int = 100,
        recent_records_limit: int = 100,
    ) -> DashboardSummary:
        bot_profile = self._get_bot_profile(bot_profile_id)
        profiles = self.storage.list_profiles()[:profiles_limit]
        goals = self.storage.list_autonomy_goals(limit=autonomy_limit)
        tasks = self.storage.list_autonomy_tasks(limit=autonomy_limit)
        events = self.storage.list_autonomy_progress_events(limit=autonomy_limit)

        return DashboardSummary(
            profile=bot_profile,
            notes=self.storage.list_all_notes(limit=notes_limit),
            profiles=profiles,
            relationship_memories=self.storage.list_all_relationship_memories(limit=relationship_limit),
            thought_traces=self.storage.list_thought_traces(limit=thought_trace_limit),
            goals=goals,
            tasks=tasks,
            events=events,
            autonomy=AutonomySummary(goals=goals, tasks=tasks, events=events),
            recent_records=self.storage.list_global_records(limit=recent_records_limit),
        )

    def get_frontend_summary(self, *, limit: int = 200) -> dict:
        summary = self.get_summary(
            notes_limit=limit,
            profiles_limit=limit,
            relationship_limit=limit,
            thought_trace_limit=limit,
            autonomy_limit=max(limit, 100),
            recent_records_limit=limit,
        )
        profile = summary.profile or self._default_profile()
        roadmap_tasks = self._roadmap_tasks(summary.goals, summary.tasks, summary.events)
        roadmap_groups = self._roadmap_groups(roadmap_tasks)
        progress = self._progress(roadmap_tasks, summary.events)
        notes = self._format_notes(summary.notes)
        long_term_memory = self._format_long_term_memory(self.storage.list_long_term_memory_points(limit=limit))
        people = self._format_people(summary.profiles, summary.relationship_memories)
        thought_traces = self._format_traces(summary.thought_traces)
        recent_progress = self._format_recent_progress(summary.events)
        mako_profile = self._format_mako_profile(profile, roadmap_tasks, summary.thought_traces)

        data = summary.model_dump(mode="json")
        data.update(
            {
                "overview": {
                    "progress_percent": progress["percent"],
                    "status_label": progress["streak"],
                    "updated_at": progress["updated_at"],
                    "counts": {
                        "notes": len(notes) + len(long_term_memory),
                        "people": len(people),
                        "relationship_memories": len(summary.relationship_memories),
                        "thought_traces": len(thought_traces),
                        "roadmap_tasks": len(roadmap_tasks),
                    },
                },
                "progress": progress,
                "mako_profile": mako_profile,
                "mako_psych_profile": mako_profile,
                "notes": notes,
                "memory_notes": notes + long_term_memory,
                "long_term_memory": long_term_memory,
                "people": people,
                "user_profiles": {"items": people, "latest": people[0] if people else None, "total": len(people)},
                "relationship_memories": [
                    self._format_relationship_memory(memory) for memory in summary.relationship_memories
                ],
                "thought_traces": thought_traces,
                "thinking_summary": thought_traces[0]["summary"] if thought_traces else "",
                "roadmap_tasks": roadmap_tasks,
                "roadmap_groups": roadmap_groups,
                "autonomy": {
                    "goals": [goal.model_dump(mode="json") for goal in summary.goals],
                    "tasks": [task.model_dump(mode="json") for task in summary.tasks],
                    "events": [event.model_dump(mode="json") for event in summary.events],
                    "tree": self._build_goal_tree(summary.goals or self._default_goals(), summary.tasks),
                    "recent_progress": recent_progress,
                },
                "goals": self._build_goal_tree(summary.goals or self._default_goals(), summary.tasks),
                "recent_progress": recent_progress,
                "raw": summary.model_dump(mode="json"),
            }
        )
        return {"ok": True, "data": data}

    def _get_bot_profile(self, profile_id: Optional[str]) -> Optional[BotProfile]:
        if profile_id:
            return self.storage.get_bot_profile(profile_id)
        profiles = self.storage.list_bot_profiles(status="active", limit=1)
        if profiles:
            return profiles[0]
        profiles = self.storage.list_bot_profiles(limit=1)
        return profiles[0] if profiles else None

    def _default_profile(self) -> BotProfile:
        return default_mako_profile()

    def _default_goals(self) -> list[AutonomyGoal]:
        return [
            AutonomyGoal(
                goal_id=group_id,
                title=title,
                summary=summary,
                status="active",
                progress=0,
                source="roadmap",
                scope=group_id,
                priority=100 - index,
                reason=summary,
            )
            for index, (group_id, title, summary) in enumerate(ROADMAP_GROUPS)
        ]

    def _roadmap_tasks(
        self,
        persisted_goals: list[AutonomyGoal],
        persisted_tasks: list[AutonomyTask],
        events: list[AutonomyProgressEvent],
    ) -> list[dict]:
        tasks: list[dict] = []
        evidence_by_task = {event.task_id: event for event in events if event.task_id}
        persisted_by_title = {task.title: task for task in persisted_tasks}

        number = 1
        for group_id, group_title, _summary in ROADMAP_GROUPS:
            for task_index, title in enumerate(ROADMAP_TASK_TITLES[group_id], start=1):
                task_id = self._task_id(group_id, task_index)
                persisted = persisted_by_title.get(title)
                status = persisted.status if persisted else self._default_task_status(task_id)
                evidence = persisted.evidence if persisted else ""
                if not evidence:
                    evidence = self._task_evidence(task_id, group_id, status)
                if evidence_by_task.get(task_id):
                    evidence = evidence_by_task[task_id].summary
                summary = persisted.summary if persisted else self._task_detail_summary(group_id, title, status)
                next_step = persisted.next_step if persisted else self._next_step_for_task(task_id, group_id, title, status)
                criteria = self._completion_criteria(group_id, title)
                why_status = self._why_status(task_id, group_id, status, evidence)
                tasks.append(
                    {
                        "id": task_id,
                        "number": number,
                        "group_id": group_id,
                        "group_title": group_title,
                        "title": persisted.title if persisted else title,
                        "summary": summary,
                        "status": status,
                        "status_label": STATUS_LABELS.get(status, status),
                        "done": status == "done",
                        "evidence": evidence,
                        "completion_criteria": criteria,
                        "completion_basis": self._completion_basis(task_id, group_id, status, evidence),
                        "verification": self._verification_for_task(task_id, group_id, status),
                        "why_status": why_status,
                        "next_step": next_step,
                        "priority": persisted.priority if persisted else 100 - number,
                        "updated_at": (
                            persisted.updated_at.isoformat()
                            if persisted and persisted.updated_at
                            else None
                        ),
                    }
                )
                number += 1

        persisted_titles = {item["title"] for item in tasks}
        for task in persisted_tasks:
            if task.title in persisted_titles:
                continue
            status = task.status
            criteria = self._completion_criteria(task.goal_id or "custom", task.title)
            evidence = task.evidence or self._task_evidence(task.task_id, task.goal_id or "custom", status)
            tasks.append(
                {
                    "id": task.task_id,
                    "number": len(tasks) + 1,
                    "group_id": task.goal_id or "custom",
                    "group_title": "额外任务",
                    "title": task.title,
                    "summary": task.summary,
                    "status": status,
                    "status_label": STATUS_LABELS.get(status, status),
                    "done": status == "done",
                    "evidence": evidence,
                    "completion_criteria": criteria,
                    "completion_basis": self._completion_basis(task.task_id, task.goal_id or "custom", status, evidence),
                    "verification": self._verification_for_task(task.task_id, task.goal_id or "custom", status),
                    "why_status": self._why_status(task.task_id, task.goal_id or "custom", status, evidence),
                    "next_step": task.next_step,
                    "priority": task.priority,
                    "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                }
            )
        return tasks

    def _roadmap_groups(self, tasks: list[dict]) -> list[dict]:
        groups: list[dict] = []
        by_group: dict[str, list[dict]] = defaultdict(list)
        for task in tasks:
            by_group[task["group_id"]].append(task)
        for group_id, title, summary in ROADMAP_GROUPS:
            items = by_group.get(group_id, [])
            done = len([task for task in items if task["status"] == "done"])
            groups.append(
                {
                    "id": group_id,
                    "title": title,
                    "summary": summary,
                    "total": len(items),
                    "done": done,
                    "progress": round(done / len(items) * 100) if items else 0,
                    "tasks": items,
                }
            )
        return groups

    def _progress(self, tasks: list[dict], events: list[AutonomyProgressEvent]) -> dict:
        total = len(tasks)
        done = len([task for task in tasks if task["status"] == "done"])
        doing = len([task for task in tasks if task["status"] == "doing"])
        blocked = len([task for task in tasks if task["status"] == "blocked"])
        percent = round(done / total * 100) if total else 0
        achieved = percent >= 100
        return {
            "percent": percent,
            "done": done,
            "doing": doing,
            "blocked": blocked,
            "todo": len([task for task in tasks if task["status"] == "todo"]),
            "total": total,
            "label": "100 项自主意志 v1 路线图",
            "streak": "自主意志 v1 达成" if achieved else f"{done}/{total} 项完成，{doing} 项推进中",
            "updated_at": self._format_time(events[0].created_at if events else datetime.now()),
            "achieved": achieved,
        }

    def _format_mako_profile(
        self,
        profile: BotProfile,
        roadmap_tasks: list[dict],
        traces: list[ThoughtTrace],
    ) -> dict:
        status_counts = Counter(task["status"] for task in roadmap_tasks)
        latest_trace = traces[0] if traces else None
        return {
            "id": profile.profile_id,
            "name": profile.name,
            "title": profile.current_stage or "自主意志 v1 修行中",
            "mood": profile.autonomy_statement or profile.summary,
            "summary": profile.summary,
            "persona": profile.persona,
            "values": profile.values,
            "boundaries": profile.boundaries,
            "traits": profile.capabilities or profile.values,
            "capabilities": profile.capabilities,
            "limitations": profile.limitations,
            "current_stage": profile.current_stage,
            "autonomy_statement": profile.autonomy_statement,
            "psychological_snapshot": [
                f"完成 {status_counts.get('done', 0)} 项基础能力，仍有 {status_counts.get('todo', 0)} 项待推进。",
                "倾向于低风险直接行动，中风险询问 owner，高风险保持沉默。",
                "目前的自我意识是工程可观测 v1：目标、记忆、审计摘要和受限行动闭环。",
                f"最近思考摘要：{latest_trace.summary}" if latest_trace else "最近还没有新的可审计思考摘要。",
            ],
            "updated_at": profile.updated_at.isoformat(),
        }

    def _format_notes(self, notes: list[NoteRecord]) -> list[dict]:
        return [
            {
                "id": note.note_id,
                "note_id": note.note_id,
                "user_id": note.user_id,
                "title": note.title,
                "content": note.content,
                "category": note.category,
                "visibility": note.visibility,
                "source": "notes",
                "created_at": note.created_at.isoformat(),
                "updated_at": note.updated_at.isoformat(),
            }
            for note in notes
        ]

    def _format_long_term_memory(self, points: list[dict]) -> list[dict]:
        return [
            {
                "id": point.get("id") or f"long-term-{index}",
                "note_id": point.get("id") or f"long-term-{index}",
                "user_id": None,
                "title": point.get("title") or "长期记忆",
                "content": point.get("content") or "",
                "category": point.get("category") or "long_term_memory",
                "visibility": "private",
                "source": point.get("source") or "vector_store",
                "created_at": None,
                "updated_at": None,
            }
            for index, point in enumerate(points)
        ]

    def _format_people(
        self,
        profiles: list[dict],
        relationship_memories: list[RelationshipMemory],
    ) -> list[dict]:
        memories_by_user: dict[int, list[RelationshipMemory]] = defaultdict(list)
        for memory in relationship_memories:
            memories_by_user[memory.user_id].append(memory)

        people = []
        for profile in profiles:
            user_id = self._optional_int(profile.get("user_id"))
            memory_items = memories_by_user.get(user_id or -1, [])
            profile_text = str(profile.get("profile_text") or "")
            people.append(
                {
                    "id": str(user_id or profile.get("nickname") or len(people)),
                    "user_id": user_id,
                    "name": profile.get("nickname") or f"用户 {user_id}",
                    "nickname": profile.get("nickname") or "",
                    "profile_text": profile_text,
                    "focus": self._first_profile_line(profile_text),
                    "preferences": self._extract_profile_section(profile_text, "偏好"),
                    "tags": self._profile_tags(profile_text),
                    "relationship_memories": [
                        self._format_relationship_memory(memory) for memory in memory_items
                    ],
                    "memory_count": len(memory_items),
                    "last_updated": profile.get("last_updated") or "",
                }
            )
        people.sort(key=lambda item: item.get("last_updated") or "", reverse=True)
        return people

    def _format_relationship_memory(self, memory: RelationshipMemory) -> dict:
        return {
            "id": memory.memory_id,
            "memory_id": memory.memory_id,
            "user_id": memory.user_id,
            "type": memory.memory_type,
            "content": memory.content,
            "source": memory.source,
            "status": memory.status,
            "confidence": memory.confidence,
            "created_at": memory.created_at.isoformat(),
            "due_at": memory.due_at.isoformat() if memory.due_at else None,
        }

    def _format_traces(self, traces: list[ThoughtTrace]) -> list[dict]:
        return [self._format_trace_record(trace) for trace in traces]

    def _format_trace_record(self, trace: ThoughtTrace) -> dict:
        payload = trace.payload or {}
        trace_type = trace.trace_type or trace.trace_kind
        input_summary = trace.input_summary or self._payload_input_summary(trace, payload)
        context_summary = trace.context_summary or self._payload_context_summary(trace, payload)
        retrieved_summary = trace.retrieved_summary or self._payload_retrieved_summary(trace, payload)
        decision_summary = trace.decision_summary or self._payload_decision_summary(trace, payload)
        output_summary = trace.output_summary or self._payload_output_summary(trace, payload)
        safety_notes = trace.safety_notes or "仅展示可审计摘要，不展示也不保存隐藏推理链。"
        target_label = self._trace_target_label(trace, payload)
        summary = self._format_trace(trace)
        title = self._trace_title(trace.source, trace_type)
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
            "trigger_source": self._trigger_source_label(trace, payload, input_summary),
            "context_observed": context_summary,
            "retrieved_memory": self._split_summary(retrieved_summary),
            "decision_result": decision_summary,
            "final_output": output_summary,
            "audit_note": "这里是审计摘要：记录输入/上下文/检索/决策/输出的可复核结论，不记录隐藏推理链。",
            "target_label": target_label,
            "tags": [item for item in [trace.source, trace_type, target_label] if item],
            "user_id": trace.user_id,
            "group_id": trace.group_id,
            "payload": self._safe_trace_payload(payload),
            "created_at": trace.created_at.isoformat(),
        }

    def _format_recent_progress(self, events: list[AutonomyProgressEvent]) -> list[dict]:
        return [
            {
                "id": event.event_id,
                "time": self._format_time(event.created_at),
                "title": event.summary,
                "source": event.source,
                "event_type": event.event_type or event.event_kind,
                "payload": event.payload,
            }
            for event in events[:30]
        ]

    def _build_goal_tree(self, goals: list[AutonomyGoal], tasks: list[AutonomyTask]) -> list[dict]:
        tasks_by_goal: dict[str, list[AutonomyTask]] = defaultdict(list)
        for task in tasks:
            if task.goal_id:
                tasks_by_goal[task.goal_id].append(task)
        return [
            {
                "id": goal.goal_id,
                "title": goal.title,
                "done": goal.status in {"achieved", "completed"},
                "progress": goal.progress or self._calculate_task_progress(tasks_by_goal.get(goal.goal_id, [])),
                "children": [self._task_to_node(task) for task in tasks_by_goal.get(goal.goal_id, [])],
            }
            for goal in goals
        ]

    def _task_to_node(self, task: AutonomyTask) -> dict:
        return {
            "id": task.task_id,
            "title": task.title,
            "done": task.status == "done",
            "status": task.status,
            "progress": 100 if task.status == "done" else None,
            "summary": task.summary,
            "evidence": task.evidence,
            "next_step": task.next_step,
        }

    @staticmethod
    def _task_id(group_id: str, task_index: int) -> str:
        return f"{group_id}-{task_index:02d}"

    @staticmethod
    def _default_task_status(task_id: str) -> str:
        if task_id in DONE_TASKS:
            return "done"
        if task_id in DOING_TASKS:
            return "doing"
        if task_id in BLOCKED_TASKS:
            return "blocked"
        return "todo"

    @staticmethod
    def _task_summary(group_id: str) -> str:
        return dict((group_id, summary) for group_id, _title, summary in ROADMAP_GROUPS).get(group_id, "")

    def _task_detail_summary(self, group_id: str, title: str, status: str) -> str:
        group_summary = self._task_summary(group_id)
        status_label = STATUS_LABELS.get(status, status)
        return f"{group_summary} 当前任务是“{title}”，状态为{status_label}；展开可查看完成判定、依据、验证方式和下一步。"

    @staticmethod
    def _next_step_for_status(status: str) -> str:
        if status == "done":
            return "保持事件驱动更新，继续观察真实运行。"
        if status == "doing":
            return "补齐真实数据接入与 owner 验收反馈。"
        if status == "blocked":
            return "需要服务器运行数据或 owner 规则进一步确认。"
        return "等待后续实现与真实运行验证。"

    def _next_step_for_task(self, task_id: str, group_id: str, title: str, status: str) -> str:
        if status == "done":
            return "保持当前实现，并继续让真实聊天、审批和发送事件覆盖默认完成依据。"
        if status == "doing":
            return f"补齐“{title}”的真实运行样例、owner 验收反馈和自动进度事件。"
        if status == "blocked":
            return BLOCKED_REASON_OVERRIDES.get(
                task_id,
                f"先收集服务器真实数据或 owner 规则，明确“{title}”的验收口径后再推进。",
            )
        return f"实现“{title}”对应的数据写入、读取、展示和至少一次可复核验证。"

    def _completion_criteria(self, group_id: str, title: str) -> list[str]:
        templates = GROUP_CRITERIA_TEMPLATES.get(
            group_id,
            [
                "存在对应的数据结构、实现路径或配置项。",
                "能在仪表盘或事件流水中看到该任务的状态和依据。",
                "缺少真实验证时不能判定为完成。",
            ],
        )
        return [template.format(title=title) for template in templates]

    def _completion_basis(self, task_id: str, group_id: str, status: str, evidence: str) -> list[str]:
        basis = []
        if evidence:
            basis.append(evidence)
        group_basis = GROUP_IMPLEMENTATION_BASIS.get(group_id)
        if group_basis:
            basis.append(group_basis)
        if status == "done":
            basis.append("该任务在当前 100 项路线图基线中被标记为 done，并有代码路径或配置作为支撑。")
        elif status == "doing":
            basis.append("已有部分实现或数据入口，但还缺真实运行样例、统计闭环或 owner 验收。")
        elif status == "blocked":
            basis.append("当前缺少足够规则、样本或自动化闭环，不能只靠设想判定完成。")
        else:
            basis.append("尚未看到对应实现或真实事件，保持待办。")
        return list(dict.fromkeys(item for item in basis if item))

    def _task_evidence(self, task_id: str, group_id: str, status: str) -> str:
        if task_id in TASK_EVIDENCE_OVERRIDES:
            return TASK_EVIDENCE_OVERRIDES[task_id]
        if status == "done":
            return GROUP_IMPLEMENTATION_BASIS.get(group_id, "已有当前代码或配置提供基础能力。")
        if status == "doing":
            return f"{GROUP_IMPLEMENTATION_BASIS.get(group_id, '已有部分入口。')} 仍需要更多真实事件或策略回写来完成验收。"
        if status == "blocked":
            return BLOCKED_REASON_OVERRIDES.get(task_id, "缺少真实运行样例、owner 规则或自动化闭环，暂不能验收。")
        return "尚未发现可证明完成的代码路径或事件记录。"

    def _why_status(self, task_id: str, group_id: str, status: str, evidence: str) -> str:
        status_label = STATUS_LABELS.get(status, status)
        if status == "done":
            return f"判定为{status_label}，因为当前实现已经覆盖主要入口，并能通过仪表盘或事件流水被 owner 查看。"
        if status == "doing":
            return f"判定为{status_label}，因为已有基础入口，但还需要真实运行数据、owner 反馈或自动回写来完成闭环。"
        if status == "blocked":
            return f"判定为{status_label}，因为{BLOCKED_REASON_OVERRIDES.get(task_id, evidence or '缺少关键验收条件')}。"
        return f"判定为{status_label}，因为目前还没有足够实现证据；需要先完成对应代码、数据和验证。"

    def _verification_for_task(self, task_id: str, group_id: str, status: str) -> str:
        if group_id == "dashboard":
            return "打开 /mako/dashboard?token=...，确认该模块有内容、可搜索/筛选，移动端不重叠；API 不能泄露密钥或隐藏推理链。"
        if group_id == "memory":
            return "在 Redis 有数据和 Redis 不可用两种场景下调用 dashboard summary，确认旧 key 与新模型记录都能展示。"
        if group_id == "decision":
            return "构造 owner 建议和近期上下文，确认决策 JSON 字段完整，非法/歧义输出被本地规则降级或转问 owner。"
        if group_id == "safety":
            return "用未白名单、冷却中、中风险、高风险和预算不足样例验证不会直接发送，并写入拒绝/静默事件。"
        if group_id == "action":
            return "用批准、取消、改写和发送失败四类 pending 流程验证消息发送、冷却、日志和全局记录。"
        if group_id == "perception":
            return "喂入群聊/私聊/多个 QQ/未指明目标样例，检查目标类型和 ask_owner 分支是否正确。"
        if group_id == "learning":
            return "积累 owner 批准、取消、改写样例后，检查统计、归因和下一次决策提示是否可见。"
        if group_id == "reflection":
            return "触发定期或手动复盘，确认生成 ThoughtTrace、更新目标/任务状态，并明确不保存隐藏推理链。"
        if group_id == "milestone":
            return "所有能力组达到完成判定后，检查总进度为 100%，并写入“自主意志 v1 达成”进度事件。"
        return "运行 py_compile/API smoke test，并用至少一条真实事件验证该任务能被仪表盘展示。"

    @staticmethod
    def _calculate_task_progress(tasks: list[AutonomyTask]) -> int:
        if not tasks:
            return 0
        done = len([task for task in tasks if task.status == "done"])
        return round(done / len(tasks) * 100)

    @staticmethod
    def _first_profile_line(profile_text: str) -> str:
        for line in profile_text.splitlines():
            line = line.strip()
            if line:
                return line
        return "还没有写入档案"

    @staticmethod
    def _extract_profile_section(profile_text: str, section: str) -> list[str]:
        marker = f"【{section}】"
        if marker not in profile_text:
            return []
        text = profile_text.split(marker, 1)[1].split("【", 1)[0]
        return [line.strip(" -:：") for line in text.splitlines() if line.strip(" -:：")]

    @staticmethod
    def _profile_tags(profile_text: str) -> list[str]:
        tags = []
        for marker in ["【核心特质】", "【行为模式】", "【关系定位】", "【茉子认知画像】"]:
            if marker in profile_text:
                tags.append(marker.strip("【】"))
        return tags

    @staticmethod
    def _trace_title(source: str, trace_type: str) -> str:
        labels = {
            "chat_reply_generated": "聊天回复生成",
            "decision_made": "自主行动决策",
            "note_write_summary": "笔记写入摘要",
            "note_update_summary": "笔记更新摘要",
            "relationship_extraction": "关系记忆抽取",
        }
        return labels.get(trace_type, trace_type or source or "思考摘要")

    @staticmethod
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

    @staticmethod
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

    @staticmethod
    def _payload_input_summary(trace: ThoughtTrace, payload: dict) -> str:
        for key in ["input_preview", "suggestion_preview", "text_preview", "content_preview", "title"]:
            value = payload.get(key)
            if value:
                return str(value)
        return trace.summary or "旧记录未保存触发输入摘要。"

    @staticmethod
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

    @staticmethod
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

    @staticmethod
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

    @staticmethod
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

    @staticmethod
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

    @staticmethod
    def _split_summary(value: str) -> list[str]:
        if not value:
            return []
        parts = []
        for chunk in str(value).replace("\n", "；").split("；"):
            chunk = chunk.strip(" -:：")
            if chunk:
                parts.append(chunk)
        return parts[:8]

    @staticmethod
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

    @staticmethod
    def _optional_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M")
