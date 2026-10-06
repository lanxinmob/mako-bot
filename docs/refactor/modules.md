> 2026-09-08 批准记录：用户选择 A 基线，批准 R0–R16 执行。下文保留原提案供追溯；当前状态以 status.md 为准。

# 逐模块重构任务单（R0–R16 已批准）

此处保留批准时的任务范围；实际完成路径与验证见 migration.md、status.md。每个模块开工必须重新读取根 AGENTS.md 指定的文档。
行号只反映 2026-09-08 扫描；执行时以方法名称、调用关系和实时扫描定位。
测试名指现有位置，R15 迁移后使用新路径；只新增当前契约缺少的关键断言。

## R0：选定基线与建立可恢复记录

- 依赖：开发者确认 plan.md 的基线及模块范围。
- 范围：版本/状态记录、隔离工作区、文档；不做业务修复。
- 动作：记录 HEAD、tracked diff、未跟踪文件清单及哈希；保护草稿副本；根据批准选择建立隔离基线。
- A 方案复制文档与扫描器进入隔离工作区；原目录不恢复、不清理。B 方案列明启动缺口后再批准最小修复。
- 验证：基线结构扫描、编译、启动导入测试和一次基线测试结果；记录环境、失败和时间。
- 交付：基线定位、草稿恢复方法、已存在问题表和首模块 PR 草案。
- 回退：只撤销本模块新建的隔离产物，原草稿原样保留；删除前核对实际路径范围。

## R1：存储后端与会话数据

- 依赖：R0；源 `src/services/storage.py`。
- 提取 `MemoryStorage`、Redis 获取/override 到 `services/persistence/backends/{memory,redis}.py`；包入口组合共享后端。
- 提取 `get_history/save_history`、全局记录到 `history.py`；发送记录与 sent_news 到 `outbound.py`。
- 保留 `StorageService` 过渡接口，显式传入同一 backend；不改变 `_memory` 的共享语义。
- 此阶段其余方法暂留原文件，允许已有超标在后续 R2/R3 完成消解。
- 验证：`test_storage_history_migration.py`、`test_redis_recovery.py`、`test_news_storage.py`、`test_outbound_dedup.py`；检查 Redis key/序列化和重连后状态。
- 回退：只撤销提取及委托，不更改已存数据。

## R2：画像、关系、笔记、提醒与治理存储

- 依赖：R1；源仍为 storage.py。
- `profiles.py`：用户/机器人画像与好感度存取；`notes.py`：笔记与长期记忆点。
- `relationships.py`：关系记忆、到期跟进；`reminders.py`：提醒持久化。
- `governance.py`：黑名单和成本存储；业务规则仍在原治理服务，不混进仓库。
- 仓库复用 R1 backend；`list_due_followups` 与关系数据共同迁移，保持日期和排序语义。
- 验证：`test_relationship_service.py`、`test_reminder_persistence.py`、`test_governance_availability.py`、`test_mako_context.py`；补必要的画像/笔记读写契约而非方法镜像测试。
- 回退：按仓库委托反向迁移，不迁移 Redis 格式。

## R3：自主任务存储与存储入口收口

- 依赖：R2。
- `persistence/autonomy/{goals,tasks,progress,traces,normalization}.py`：分别提取目标、任务、进度、轨迹和兼容解析。
- `_derive_trace_fields` 与 trace 类型/负载语义保持；归一化纯函数不依赖 NoneBot。
- `persistence/facade.py` 保留显式 `StorageService` 委托；`persistence/__init__.py` 导出入口。
- 更新内部导入；旧 `services/storage.py` 只临时导出，R14 清除；根 persistence 预计 9 个文件（含 __init__），backend 和 autonomy 分包。
- 验证：`test_autonomy_runtime.py`、`test_mako_context.py`，以及相关 Dashboard 任务/轨迹输入输出契约；核对空数据与旧载荷。
- 回退：恢复原 façade 和导入，不能以动态 `__getattr__` 掩盖遗漏。

## R4：Dashboard 静态路线图资料

- 依赖：R0（建议在 R3 后执行以减少后续导入调整）。
- 源 `web/dashboard/service.py` 顶部约 400 行静态定义；先枚举常量引用。
- 移入 `roadmap/{catalog,evidence,defaults}.py`；按语义分配任务目录、解释/依据、默认值，单文件 <=400。
- 不把代码迁成需要新加载器/校验协议的任意 JSON；保持原常量形状与默认状态。
- 验证：相同固定输入下 `get_frontend_summary` 的路线图、默认目标、进度字段等价；测试已有覆盖不足时加一个固定契约样例。
- 回退：常量回移，接口与资源均不变。

## R5：Dashboard 数据组装与展示转换

- 依赖：R3、R4。
- `presenters/{profile,memory,people,traces}.py` 提取相关 `_format_*` 及负载安全转换。
- `roadmap/{progress,tasks}.py` 提取任务树、进度、完成依据与下一步说明；复用 R4 常量。
- service.py 仅保留取数与组合；尽量构造一次输入快照，保持 limit、排序及缺省值。
- 路由文件和 API schema 不变，拒绝把鉴权塞进 presenter。
- 验证：空数据、完整数据、旧 trace 三类 summary 契约；`test_application_boot.py` 中鉴权/安全头相关断言；必要时补响应一致性测试。
- 回退：调用委托回移，无数据库/API 迁移。

## R6：检索上下文流水线

- 依赖：R0；源 `services/chat_context.py`。
- `retrieval/models.py`：SearchOutcome、SearchSource、VerifiedClaim。
- `planning.py`：查询规范化、时间/图片提示、fallback；`ranking.py`：来源筛选与排序。
- `verification.py`：事实校验、claim 解析；`context.py`：SearchContextBuilder 编排。
- 图像限流及 ChatContextBuilder 留到 `chat/context.py`；时间与历史小函数按唯一职责分配，禁止工具包互相回引。
- 不更换搜索源、打分或事实验证算法；保持超时、并发限制、失败提示和指标计数。
- 验证：`test_chat_context.py`、`test_search_metrics.py`、`test_search_security.py`、`test_ollama_search.py` 中相关用例。
- 回退：恢复 builder 导入与实现，不改变外部 API 配置。

## R7：工具执行策略与处理器

- 依赖：R6；源 `services/tool_executor.py`。
- `tools/models.py` 保存结果类型；`policy.py` 保存去重、启用判断、治理与预算判断。
- `media.py`：图片、语音及临时文件生命周期；`text.py`：翻译、摘要/检索类；`local.py`：天气/地图/笔记等现有调用。
- `executor.py` 保留显式分发和错误聚合，原调用顺序与结果合并语义保持；注册表只在有真实扩展需求时引入。
- 图片下载安全与文件清理仍使用原适配器；禁止因移动失去 finally 清理或权限检查。
- 验证：`test_tool_executor_policy.py`，图片安全中的临时文件与工具执行用例；验证拒绝时不触发外部副作用。
- 回退：处理器回并，保持 IntentDecision 与 ToolExecutionResult 接口。

## R8：聊天生成引擎

- 依赖：R3、R6。
- `chat/models.py`：ChatRequest/ChatReply；`messages.py`：提示组装；`history.py`：历史规范化与追加。
- `facts.py`：来源链接、事实回答验证与 fallback；`engine.py`：调用模型、生成和 commit 编排。
- 不借迁移改变群画像策略、提示词或静默行为；A 基线的这类需求留待 F1。
- 保留注入存储/检索方式和调用时序，防止 generate 导致重复提交历史。
- 验证：`test_chat_engine.py`、`test_chat_policy.py`、`test_mako_context.py`；覆盖事实来源、历史隔离及失败路径现有契约。
- 回退：恢复引擎实现与内部导入，模型配置不变。

## R9：聊天插件与应用编排

- 依赖：R7、R8；源 `plugins/chat.py`、chat_delivery.py、chat_reminders.py。
- `plugins/chat/__init__.py` 只注册；`ingress.py` 规范化事件；`commands.py` 注册提醒/关系命令。
- `delivery.py` 与 `reminders.py` 吸收原插件辅助文件，保持显式导入，避免自动发现两次。
- `services/chat/pipeline/{workflow,admission,execution}.py` 分离会话锁/批次调度、治理准入、工具到发送的编排。
- 插件注入事件适配后的输入、发送回调和存储；纯策略不持有 Matcher。
- A 基线保持原参与机制；B 基线需先加 F1 的群状态拆分且明确未完成行为修复清单。
- 验证：`test_chat_plugin_import.py`、`test_chat_delivery.py`、`test_chat_rhythm.py`、`test_reminder_domain.py`；用两个交错事件核对锁与注册无重复。
- 回退：原子恢复 chat.py 与旧辅助路径，不能同时存在同名模块和包。

## R10：自主行为模型、状态与纯策略

- 依赖：R3；源 `plugins/autonomy.py`。
- `services/autonomy/models.py`：Decision/Pending/Target/Whitelist 数据结构。
- `repository.py`：allowlist、cooldown、pending、日志状态；保留现有存储格式与失效时间。
- `parsing.py`：JSON、目标与命令解析；`policy.py`：是否允许、是否审批与触发判断。
- 将 driver/matcher/scheduler 依赖留在插件；服务显式接收 settings、clock 和 backend。
- 验证：`test_autonomy_runtime.py` 中目标识别、白名单、审批/拒绝、冷却用例；不实际发消息。
- 回退：提取部分回并，状态不迁移。

## R11：自主行为规划、执行与插件注册

- 依赖：R10、R7。
- `services/autonomy/planning.py`：LLM 决策/润色；`execution.py`：动作执行；`workflow.py`：审批到执行状态流。
- `plugins/autonomy/{__init__,owner,scan}.py`：注册、Owner 指令和周期扫描。
- 保持审批 token、目标权限、冷却更新、失败反馈和任务完成的原有顺序；不趁重构扩大自主权限。
- 检查 scan 的 job ID 与注册次数；服务不得再次调用 `on_message` 或 scheduler 装饰器。
- 验证：`test_autonomy_runtime.py`、`test_governance_plugin_import.py`、启动导入检查；模拟批准/拒绝/失败闭环。
- 回退：原子恢复 autonomy.py，确保新旧定时任务不共存。

## R12：Dashboard JavaScript

- 依赖：R5；源 `static/assets/dashboard.js`（543 行）。
- 保留 dashboard.js 为 ES module 入口；`js/{api,state,format,render,events}.js` 按请求、状态、转换、渲染、事件拆分。
- 若 render 本身超标，再按 overview/memory/roadmap 等视图建子目录，不机械按行切开函数。
- index.html 改同源 `type="module"` 引用；保留唯一静态资源目录，无 bundler、无第二套前端。
- 保持 token 行为、错误提示、导航、过滤和内容转义；不修改 summary schema。
- 验证：受控数据下登录/401、导航切换、搜索/筛选、空数据渲染；检查模块路径、MIME、CSP 与 wheel 资源（最终打包在 R16）。
- 回退：恢复单 JS 和 script 属性，后端不变。

## R13：Dashboard CSS

- 依赖：R12；源 `static/assets/dashboard.css`（784 行）。
- `css/{base,layout,components,views}.css`；dashboard.css 只保留按原级联顺序的入口导入。
- 共享变量集中 base；断点随相关规则迁移或保持统一且有顺序说明。
- 不重新命名全部 class，不做视觉改版；前后对比同样页面状态和宽度。
- 验证：桌面/窄屏的概览与长列表，布局溢出、弹层及焦点可见性；不为样式移动重复运行 Python 全套。
- 回退：按原顺序恢复 CSS，HTML class 保持。

## R14：其余服务归类与导入收口

- 依赖：R1–R13。只移动以下小文件及引用，不改其业务逻辑。
- `chat_policy/chat_rhythm/response_style` → `chat/{policy,rhythm,response_style}`。
- `search/search_metrics` → `retrieval/{client,metrics}`。
- `affinity/knowledge_precipitation/mako_context/notes/relationship/vector_store` → `memory/` 同名文件。
- `http/llm/gemini/image/language/emoji/amap/weather` → `integrations/` 同名文件。
- `chat_audit/outbound_dedup/reminder` → `delivery/{audit,dedup,reminder}`；新增 outbound 草稿仅 F1 接入。
- `redis.py` 的客户端实现并入 R1 的 `persistence/backends/redis.py`，保留单一连接/恢复状态，移除 R1 的旧导入桥梁；不再二次移动后端目录。
- `governance` → `governance/service.py`；`news` → `information/news.py`。
- 删除已无引用的过渡旧路径；核对配置插件名字、`pyproject.toml`、外部脚本和 monkeypatch 路径。不修改小而清晰的 core/models/utils。
- 验证：全仓旧导入搜索、测试收集、编译与核心插件导入；这一步暂不再重复全量行为测试。
- 回退：依据迁移映射恢复全部路径与导入，不混入格式化差异。

## R15：测试目录归类与媒体测试拆分

- 依赖：R14。
- `core/`：application_boot、bootstrap、config_safety、llm_config。
- `chat/`：chat_context、chat_delivery、chat_engine、chat_plugin_import、chat_policy、chat_rhythm；group_conversation 属 F1。
- `persistence/`：storage_history_migration、redis_recovery；`delivery/`：reminder_domain/reminder_persistence、outbound_dedup（dispatch 属 F1）。
- `autonomy/`、`governance/`：各自现有 runtime/availability/plugin_import；`tools/`：intent_service、tool_executor_policy。
- `memory/`：relationship_service、mako_context、knowledge_precipitation；`information/`：news、news_storage。
- `retrieval/`：ollama_search、search_security、search_metrics。
- `media/`：把 test_image_safety.py 拆为 config、dimensions、download、temporary_files、context、edge_cases 测试；复用小型 conftest fixture。
- 测试 Compose 保留 test 根；禁止根 conftest 重复导入业务服务导致全局初始化。
- 验证：迁移前后 `pytest --collect-only -q` 数量与用例名称映射一致，检查相对路径和 fixture scope；实际全套执行留 R16。
- 回退：按测试路径映射恢复，不删除重复命名但不同场景的测试。

## R16：集成评审与文档闭环

- 依赖：R15。
- 重新扫描所有手写源码/测试/前端/文档；超标项必须已消解或有开发者明确例外。
- 检查兼容导出无残留、包依赖方向、插件唯一注册、静态目录唯一及 Agent 文档实际一致。
- 一次性跑 CI 等价检查：Python 兼容环境、编译、完整 pytest、wheel 与资源；环境不支持的项明确列出。
- 使用独立评审 Agent 综合前面模块；未恢复额度则这项标未完成，不能以主 Agent 自评替代。
- 更新 project.md、迁移映射、状态、扫描报告和实际 PR 说明；说明无真实 QQ 试用证据。
- 交付开发者验收后，才进入后续业务功能任务。

## F1：重构完成后的功能草稿迁移（2026-09-13 开始）

- 将群状态草稿拆到 `services/chat/group/{models,window,policy,candidates,service}.py`，将 participation_model 独立为 adapter；更新 import 和测试。
- 把 outbound 草稿接入 delivery 包，把发现功能按 catalog/provider/renderer/plugin 契约整理；保持每目录 <=10 文件。
- 按原工作区快照逐项移植配置、提示词、接入、发送与测试；不覆盖已经重构的文件。
- 之后继续未完成的自然度/功能工作，真实期刊、网站鸟类资料与 600秒/60条上下文偏好保持。
- 每项重新读取文档，单列行为变更、实际测试与独立评审；不把草稿存在当成需求完成。
