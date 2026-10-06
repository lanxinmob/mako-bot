# R16 恢复后的独立综合评审

## 开工与证据归属

- 评审日期：2026-09-13，Asia/Shanghai；规范重读及主要证据核对在 15:01 前完成，随后补核对代码及基线时序。
- 模块：R16 独立综合；工作区 `D:/vscode workplace/fun/bot/mako-bot-refactor`。本轮实测 HEAD 为 `8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9`，评审对象包含尚未提交的重构文件。
- 已重新读取根 AGENTS.md、project.md、development.md、plan.md、modules.md、status.md，并读 audit.md；docs 下未找到更具体 AGENTS.md。
- 唯一写入本文件；业务代码、其他记录、CI 配置均由本评审只读。未运行全套测试、应用、真实 env/QQ/Redis/外部 API，未提交。
- 保留契约：A 基线行为、共享存储及数据格式、插件注册、提示词与工具规则、发送/提交次序、Dashboard 接口和资源。后续防刷屏属于独立行为变更。
- 本人阅读 core.md、integration.md，且直接用 Codex app read_thread(includeOutputs=true) 读取服务任务 `01a08675-e990-7f83-af28-cc64bb8695b2` 的完整可用页及成功命令，核对命令正文与退出码。随后对照主 Agent 恢复的 services-recovered.md，三条成功输出吻合。
- 服务任务最终额度错误不抹去已经执行的独立工作；但它没有留下最终意见。本文件是本轮新形成的综合判断，不是替该任务补写或转述一个不存在的“最终通过”。

## 综合结论与 R16 收口

**在所列证据与当前代码核对范围内，未发现尚未修复、可确认的新增重构回归；同意 R16 以附带基线缺陷和验证限制的形式收口。**

这里不是“整个项目没有缺陷”：存储显式注入的重构 P2 已有成功复查；本次补发现的 CI 历史对象依赖已由主 Agent 修正。其余四类行为缺陷有基线同源证据，应单列后续修复，不能归罪于结构拆分，也不能用前后等价通过掩盖问题。

R16 的技术独立综合环节可标完成。状态文档仍需由主 Agent 更新旧的“待评审/中断”表述、链接本报告及恢复记录，并保留验证限制；这属于收口交接，不要求重复整套测试。本人没有修改状态，也不声称该文档交接已经完成。

用户已要求独立评审后继续群聊功能；完成上述交接后，可按已有授权进入 F1，逐项迁移并整理草稿，先做群聊参与、沉默、过期候选与发送节奏。无需把本报告解释成部署、实际 QQ 发送或实群自然度验收授权。

## 服务探针覆盖及不能推出的结论

| 原始成功命令 | 可确认覆盖 | 局限 |
| --- | --- | --- |
| exec-32cfb0e3-a2ad-46e4-a33f-f26223536df0，exit 0 | R8 13 个归一化函数体；R7 9 个方法及 17 个分支；intent 5、search 11、metrics 7、Redis 2 个方法精确 AST；7 个 dataclass/default factory | 归一化替换依赖及提取调用名，函数体一致不证明构造/绑定/所有运行路径。前一次 `_next_history` 比较失败不计通过，修正映射后的成功命令才是依据 |
| exec-7cf04468-7cea-4cfc-93d2-7a5d82351f25，exit 0 | 注入 setter 两种顺序、合成 session 隔离、默认共享内存身份、provider 更新及显式 None/client 覆盖；R6 8 场景；R8 5 场景 | 实测 Python 3.13.5；不是 Python 3.10 或真实 Redis 恢复测试 |
| exec-5dea8505-86ff-4341-ade4-83c98986f17c，exit 0 | R7 禁用/治理/输入/预算拒绝，未配置/异常/超时/成功/不支持/无效图像；3 种临时文件生命周期 | 大部分动态分支用翻译或图片替身；不是所有 17 种工具的实际适配器验证。文件、MessageSegment、unlink 被替换，没有真实磁盘清理证明 |

R6 的 8 种情形为 supported、provider_error、unreadable、one_domain、verify_error、conflicting、bad_ids、url_error，比较 outcome 和指标调用。R8 为 plain、failed_search、verified、validator_error、correction，比较提示、回复及历史，断言 generate 不保存、commit 显式保存，检查他人 note 与过期关系内容过滤。

进一步审查命令正文得到以下边界，恢复输出的 PASS 不能替代这些说明：

- 存储 P2 通过 `object.__new__` 后设置 redis/settings 验证，禁止隐式 get_settings；这证明兼容注入路径修复，不表示普通 `StorageService()` 构造不读配置或不尝试 Redis。默认共享内存是设计契约，不是每个实例天然隔离。
- `gather` 改为顺序 await，`wait_for` 直接 await，`to_thread` 直接调用，coroutine runner 要求无真正挂起。所谓 timeout 场景是替身抛 TimeoutError；不能证明实际截止时间、取消传播、并发限制或后台线程停止。
- 旧模块由固定 SHA 读取，导入映射到当前依赖，并非完整旧环境。共同依赖中的缺陷可能同时影响两版；因此结合独立 AST、core/integration 和当前接线审查，而非把差分结果视为全系统等价证明。
- R6 关闭模型规划并注入 search/fetch/verifier；未覆盖真实规划模型、HTTP、图像限流并发或真实验证器。R8 的模型也为替身；历史合成字符串含转义换行，不能单凭该探针认定真实换行的旧 enrichment 清除分支全部跑到。
- 工具测试直接调用 `_execute_decision`，不等于动态验证 run 的 semaphore、聚合或多个任务并发；run 另有 AST 证据。write_error 的“通过”恰好确认两版都未追踪残留文件。
- core 的异步取消/竞争探针与上述同步 runner 不同，能支持它报告的特定交错；仍不能扩展为真实传输、多进程或 Redis 原子性证明。

## 本轮独立检查的关键连接

1. `plugins/chat/__init__.py → ingress → runtime.workflow → ChatWorkflow` 接线存在；runtime 的同一 storage 传入 ChatEngine、关系、治理和节奏服务。workflow 先批次再会话锁，execute 顺序仍为工具、上下文、预算、生成、回复、额外消息、提交；finally 调用工具清理。
2. `persistence/facade.py` 的所有仓库委托使用 self.backend；兼容 backend 属性使用 `StorageBackend(initialize=False)`。后者 settings 懒读取、redis setter 锁定 override，普通 provider 可刷新，memory 指向同一个 memory_store。与成功 P2 探针相符。
3. `chat/context.py` 使用当前 `retrieval.context.SearchContextBuilder` 和同一个 SearchOutcome 类型；结果经 EnrichedChatInput 进入 pipeline 的 ChatRequest。engine 在 required 且失败时先返回 fail-closed，不调用模型；MessageBuilder、history、facts 的提取方法和显式 commit 绑定仍在。
4. ToolDependencies 默认指向当前 integrations/retrieval 适配器，media 使用同一执行器传入的 track 回调；图片和 TTS 都在写文件后才追踪，解释了基线清理缺口。
5. autonomy runtime 组装 repository/policy/context；Owner rule 限 enabled、私聊和 owner，Owner 处理器调用 execution.send_action；成功发送之后才费用、冷却和去重，Owner await 返回后删除 pending。该连接保留，竞争与提交缺口也保留。
6. 本轮 stdin 静态探针解析当前 135 个 src Python 文件，所有 `src.*` 绝对 import 模块路径均可解析，exit 0；不导入应用。此检查不证明符号存在、动态导入或插件热重载唯一性。
7. 直接 `git show` 重读基线 chat/autonomy/tool_executor 的相关顺序：批次写入→sleep→删除、主发送→附件→commit、批准 await 后删除、发送后费用及冷却，以及图片/TTS 先 write 再 track 均已有。一次输出因 GBK 中断，显式 UTF-8 重跑的基线时序提取成功；未把中断命令算完整通过。

core.md 的注册/锁/取消评审和 integration.md 的 Dashboard、导入迁移、测试保留与 wheel 评审可合并采信；本人未重新运行其探针，不冒充自己动态复现了那些结果。integration 对 151 个期望资源的复核与早期 status 的 150 个路径统计属于不同记录口径，不合并成一个本轮实测数。

## CI 修正复核

已读取 `.github/workflows/ci.yml`、`test/dashboard/test_contracts.py`、`r5_contract.py` 的固定基线调用，以及 `records/integration/review-recovery.md`；并核对当前 CI diff。

- pytest 确实启动 r5_contract.py，后者 `git show 8fdb8e...:src/web/dashboard/service.py`。新增契约测试使 CI 依赖历史对象；原先未显式配置检出深度，后续浅检出可能缺失基线。
- 当前 checkout 的 with 块已增加 `fetch-depth: 0`；其余 matrix 3.10/3.13、安装、编译、wheel、pytest 未被删除或放宽。该修改针对已识别的历史对象前提，静态复核接受。
- 此项应归类为重构新增测试的 CI 集成遗漏及已修正，不能列为原产品基线缺陷；尚无远程 CI 成功运行证据。固定 SHA 仍要求发布仓库保有对应历史，不表示任意源码压缩包都能运行该历史比较测试。
- 最新 276 文件/257 文本、0 超标及 git diff --check 通过由主 Agent 本轮提供；不冒充本人重跑。早期 audit.md 的统计快照不能当作此刻文件总数。

## 基线缺陷后续处理建议

以下均按 P2 记录；编号与总体功能模块 F1 无关，不是本轮新增回归。R16 不混入这些行为修复。

| 项目与证据等级 | 后续最小处理方向 | 必要验收 |
| --- | --- | --- |
| B1 审批无原子认领：core 的双批准/批准取消双版本探针，当前及基线时序复核 | pending_id 认领；同目标发送边界内重查冷却与去重；取消报告真实执行状态。不要简单提前删除而丢失失败记录 | 同 pending 仅发送一次；两种取消交错明确；scan/Owner 同目标竞争；失败不盲目重发 |
| B2 防抖取消残留：core 双版本探针及本人基线/当前核对 | 在 guard 下按批次身份与版本清理；旧任务不能误删或认领新批次。优先纳入群聊候选迁移 | 新任务取消无残留；旧版本取消不影响新版本；下一条不混入已取消文本与时间；锁等待/生成取消分别验证 |
| B3 发送后提交不一致：core 静态发现，本人双版本顺序复核，未动态注入该阶段故障 | 分开记录主发送、附件、历史、费用及未知传输结果；已发送待补记不得再次外发；审计不能在 commit 失败后声称已提交 | 主发送成功但附件/费用/历史失败时状态准确，重试只补记；明确 to_thread 启动后取消不能撤销写入 |
| B4 临时文件 write 失败未追踪：服务图片合成差分探针，本人核对图片与 TTS 双版本代码 | 文件创建后尽早登记，覆盖 write/close/消息段失败，Windows 关闭句柄后清理；保留成功时发送完成才删除 | 图片和 TTS 的写入/关闭/消息构造失败均清理；成功文件发送前仍存在；清理可重复。TTS 扩展目前是静态判断，非原探针动态覆盖 |

建议 F1 先落实 B2 及可丢弃候选生命周期，再将 B1/B3 纳入共享发送状态设计；B4 作为独立、小范围资源修复，不必等群聊全部完成。每项修复另列行为差异及针对性验证，不以“保持基线”作为永久搁置理由。

## 验证边界与交接

- Python 3.10.20 全套 221 passed、编译、打包及浏览器多状态对照来自既有实施记录；本轮综合未重跑。3.13 的首轮失败与修复后局部通过保持原记录，不能重写成一次全绿运行。
- 未验证真实 QQ、Redis、模型、部署、实群自然度、安装 wheel 后启动或远程 CI；这些不属于本轮“未发现新增回归”的保证范围。
- 本轮新运行仅为只读源码/AST/基线提取；唯一产物为本报告。后续业务代码改变后应按改变范围重新验证，不能沿用本报告作为新功能通过结论。
- 交接结论：技术评审支持 R16 收口并继续已授权的群聊功能；保留上述基线缺陷、CI 未远程实跑及证据归属，更新状态后按映射迁移草稿，不整包覆盖新结构。
