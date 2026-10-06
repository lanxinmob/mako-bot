# H1d 第二项：实际入口、恢复扫描与 Owner 独立评审

## 开工、授权及结论

- 首轮文档/HEAD 时间核对为 2026-10-05 23:58:25 +08:00，独立评审延续至 2026-10-06；此前未参与实现。重读根 AGENTS.md、project/development、plan/modules/status/audit、B3 的 H1 约束、H1d/H1-owner，以及 snapshot/session-plan/synthesis/effects 四份独立报告。按用户声明无更具体 AGENTS；未重新审旧快照、会话 CAS 或目标 Lua。
- 唯一允许持久写入：本文件 `docs/refactor/records/review/resumed/history/entrypoint.md`，不超过 400 行。生产文件自用户声明的 23:48 冻结；17 份本分项生产文件初读与 00:06:57 哈希一致。主 Agent 的说明/扫描变化不属于本评审改动。
- 保留已批准契约：发送前计划失败暂停回复并保留生成费用；session 冲突待核对、global 独立；sending 超过五分钟只分类 unknown、不重发，原 token 可晚 ACK；人工已送达而实际时间未知时两历史 needs_review、不用核对时间补造；仅 Owner 私聊可操作，自主关闭仍可核对；人工结论不可被晚 ACK 覆盖。
- **结论：本分项暂不通过，发现 1 项 P2（E1：worker 故障被折叠为普通 outcome，恢复游标仍推进）；未发现新增 P1。Owner 人工分支、来源防御和所查主回复接线未发现其他新增 P1/P2。P3 为新增证据固化建议。**
- 本结论仅绑定下列未提交工作区文件 SHA256。HEAD `8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9` 是原基线，不能代表新实现。不能据本报告给完整 H1、P6/G2、生产持久性或 QQ 体验出通过结论。修复须交后续综合/实施单元，本评审未改变实现。

## P2 / E1：实际 worker 存储故障未阻止扫描游标前进

定位与触发：

1. `history_delivery/discovery.py:50–64` 只在 classify/run_action 抛出可用性异常时阻止返回下一游标；正常返回的 outcomes 按 len 计入两任务预算，然后推进键位置/SCAN 游标。
2. `history_delivery/worker.py:60–64` 把 claim 的 EffectUnavailable 和 EffectNeedsReview 都折叠成普通 `unconfirmed`；:42–48 把 finish/defer 的同两类异常折叠成 `settlement_unconfirmed`。这些字符串没有向扫描器保留“可用性故障/坏证据”的区别。初始 inspect/classify/SCAN 的故障确会抛出，不能把这条正常关闭路径推及上述阶段。
3. 实际 `plugins/chat/recovery.py:107–112` 收到成功返回的 HistoryPage 后更新 `_history_cursor`，不会走保留分页位置的异常分支。因此本页一个合法 sent 的认领失败，可被当成两个普通尝试后跳到下一页。

新 probe A 使用真实 HistoryScanner、HistoryWorker、HistoryEffects、create/begin/sent 与隔离 Redis；仅在任务 claim 或 finish 的客户端 EVAL 边界注入连接异常，固定 SCAN 返回以控制分页。实际结果：

| 故障阶段 | run_page('17:0') | 保留的实际任务 | 实际恢复函数正文 |
| --- | --- | --- | --- |
| claim EVAL 前连接故障 | outcomes=session/global 各 unconfirmed；next_cursor='23:0' | 两项 pending；无目标历史写入 | 再次遇到 claim 故障仍把 _history_cursor 从 '17:0' 改成 '23:0'；没有历史恢复暂停 warning |
| finish EVAL 前连接故障 | outcomes=session/global 各 settlement_unconfirmed；next_cursor='23:0' | 两项 leased；目标已幂等写入，全局一条 | 随后调用正文也推进至 '23:0'，但这次遇到未到期租约而返回 not_claimed；不冒称正文再次执行了 finish 故障 |

影响：没有复现重发、覆盖新历史或删除永久证据；动作仍可在后续扫描回绕/租约到期后恢复。但本页故障不会让周期调用保留位置，重新发现依赖全库扫描进度；永久记录积累时会增加补记延迟。这违反本项要求的“故障不跳游标”，不能以“证据还在”当成可靠恢复已验收。

**必要修复：** 给扫描调用保留结构化故障种类，或在有界尝试完独立兄弟任务后向扫描器传播 EffectUnavailable；扫描器在该类故障时不得返回越过该页的成功游标。保留 session/global 独立处理及稳定 effect ID，不能释放仍可能写入的线程租约、重发或清证据。不要对所有 unconfirmed 一律永久停页，因为该字符串当前也包含坏证据；坏键仍应能报告 needs_review 后继续。补一个使用真实 worker 的新短回归，分别核验 claim/settle 可用性故障与坏记录的分页区别。

现有 `test_history_discovery.py:59–68` 只用 run_action 直接抛 EffectUnavailable 的替身；`test_recovery_adapter.py:79–99` 同样令整个 HistoryScanner 抛错。二者证明调用方的异常分支，没有覆盖实际 worker 在认领/收尾处吞成字符串的接口差异；本轮没有复跑它们。

## 契约核对与限制

| 核对项 | 当前证据与结论 |
| --- | --- |
| 请求与原快照绑定 | execution.py:38–39 从显式 runtime.read 取得快照和独立 messages 视图；:95–109 把同一对象放入同一局部 ChatRequest；:137、176 使用此 request 和其 generate 返回的 reply。runtime.py:46–51 冻结原 snapshot、reply.text/history、同 user/group、bot、裁剪参数和时区，不发送后重读。实际 ChatEngine.generate 最终调用 next_history(request,text)，保留已有纠错/正文处理规则；仅作调用关系检查，不重新评审生成/快照模块。 |
| 真实依赖注入 | ChatServices.__post_init__ 默认创建 ChatHistoryRuntime；plugins/chat/runtime.py 用真实 services 构造 workflow，ingress.py 的 QQChatTransport.reply_recorded 透传 before_send/on_ack 到 send_reply。没有在 probe 导入这些注册/实例化入口，不声称实际应用启动验证。 |
| 发送准入一次 | runtime.py:53 只用首次 create 返回 token；:61–70 在传输 callback 内 await begin，随后再检查原 incoming.is_current。delivery.py:66–88、100–114 的群/私聊实际 send 回调先 admitted 再唯一一次 matcher.send；群成员渲染/排队在 begin 之前。Lua begin 只接受 prepared，同 token 重复 begin denied；不存在从 inspect/扫描恢复发送权限的接线。 |
| await 后 guard | runtime.py:70 检查原候选；adapter admitted 在 await before_send 后再检查其 guard（含异步 guard），通过后直接进入 matcher.send。未刷新候选 token。源码和新增集成测试 :157–174 一致；本轮只有静态证据，没有重跑该场景或整套 dispatcher。 |
| ACK 及取消 | adapter 私聊 :83–85、群 :103–106 只有 acknowledged_result 真时同步调用 on_ack；群 on_sent 在其后。runtime.py:72–75 首次冻结 time_ns 的毫秒值，:83–95 finally 用同值保存 sent，无重发/模型调用。ACK 后普通异常不发失败 notice，CancelledError 继续传播且进入 finally；现有第九项 :222–250 覆盖一次 ACK 后取消、后台消费原时间。重复取消/进程被杀/ACK 尚未持久即崩溃没有独立实测保证。 |
| 写后丢响应 | runtime sent SET 的响应丢失不会重发；即使 sent_recorded=False，consume 也通过持久任务重新确认资格，不凭内存 ACK 直写目标。当前 :178–200 测试覆盖已落盘 sent 丢响应、时间不变及恢复无二次发送；仅阅读，归属主 Agent。若 SET 未落盘或 ACK 时间因进程退出丢失，恢复不能猜值，应 unknown/人工待核对；没有证明所有 ACK 都可持久收尾。 |
| 普通旧 commit | completion.py 只调用 history_delivery.consume，并独立记附件/审计；execution.py 无 chat_engine.commit/get_history，定向搜索普通聊天源码确认 commit 仅保留定义。实际入口测试 :85–87、248 有旧调用禁止断言，未复跑。其他后台/审批写入者及旧运行进程不在本项清理范围。 |
| 独立恢复阶段 | recovery.py 为历史单独取 Redis/try/游标，注册 30 秒、max_instances=1/coalesce。历史阶段不取 bot、不依赖原发送截止或自主开关、不传模型/QQ；前面各阶段抛异常仍能继续历史。其余阶段长期阻塞的时延没有保证。真实扫描与 worker 的故障传播缺口见 E1。 |
| 有界发现和坏键 | discovery.py 每页访问最多 10 键、返回最多 2 个任务尝试；保留原 SCAN cursor+offset、空非末页和超量键尾部。非 UTF-8 键以 surrogateescape 保留后经精确 ID 正则跳过；EffectNeedsReview 的坏记录不阻断后键。COUNT=10 不是 Redis 返回/排序内存量硬上限；变化键空间可能重复或遗漏，分页不是快照。 |
| unknown / 人工 / abandoned | worker 只处理 sent 且可认领任务；tasks.claim/_settle 显式限定 transport。人工 sent 两项 needs_review、result=time_unconfirmed、无租约；abandoned 两项 dormant。classifier 对非 sending 直接 unchanged，Scanner 不为人工状态写历史。probe B 验证来源防御在 EVAL 前关闭；现有人工两态 scan DUMP 检查仅阅读，不计本轮执行。 |
| 五分钟分类 | reconciliation.py:6–25 的合法 delivery/raw CAS/PTTL=-1 条件下，仅 now-begun>300000 标 unknown 并保存原因；不更换 token、计划或激活任务。等于五分钟仍 unchanged；延迟依扫描，不保证第五分钟立即核对。runtime/恢复不自动重发；晚 ACK 的竞争由原字节 CAS 决定。分类专属旧测试未读/未复跑，此项静态核对不冒称新增运行。 |
| Owner 鉴权与自主关闭 | owner.autonomy_rule/process_owner_private 先要求 PrivateMessageEvent 与配置 Owner ID；delivery_owner.process_delivery_command 另复核。history 命令在自主 policy 检查之前处理，未把关闭自主当成禁止核对。history_feedback 的底层 API 接受 operator_id，实际授权来自这些插件 gate；不把存储格式校验当鉴权。现有实际 Owner 两测试及 manual 两态路由均只读。 |
| Owner 信息与错误反馈 | review/format_history 只显示动作 ID、bot/目标、发送来源/状态和两历史状态/次数/固定原因，无正文/raw/token。人工 sent 明确实际时间未知；放弃不等于未送达。读取故障/写后丢响应明确“本次核对结果未确认”，不冒称未写入；probe B 验证 actual history_feedback 的已落盘人工 SET 丢响应。列表不分类/认领，坏记录显示待核对。 |
| 人工终态及 raw CAS | reconcile 先解码 delivery 与 task metadata，再在 RECONCILE 中校验类型/原字节/永久 TTL，只 unknown 首次写结论；同结论保留原 operator/time/raw，相反结论 denied。delivery_scripts.py:29 的 owner 拒绝在任何 transport 操作之前。probe B 补 Owner 在 ACK GET/EVAL 之间获胜的 sent/abandoned 两态，旧 raw ACK changed、重读后 ACK denied，人工 raw 不变；相反方向现有 :74–85 仅阅读。 |
| 严格人工字段及 TTL | delivery.py:44–64 要求 owner source、匹配 sent/abandoned 结论、正 ASCII 数字操作者、严格时间、显式 delivered_at_ms=null、空 task_meta、两项保守状态；缺字段/伪 pending/其他 source 均关闭。人工来源不能伪作 transport；旧 transport 缺 source 仍兼容。所有修改 Lua 保留 PTTL=-1；probe B 的读取后加 TTL 被拒且 DUMP/TTL 不变。GET/inspect 本身不查 TTL，不是消费或发送授权。 |
| 老版本兼容说明 | H1-owner.md:9、17 已说明 v1 的人工分支、缺 source 的旧 transport 兼容、旧消费者不理解人工状态须故障关闭、切换/回退停旧进程并保留证据。按 effects.md 的旧解码，人工 sent 因 null ACK 拒读、abandoned 因未知 state 拒读；不保证任何更旧/自定义消费者都安全。仅核对说明及已评审版差异，不重新运行旧消费者或生产部署。 |

## 相对第一分项的共享差异

- effects.md 已核对的 tasks.py 为 137 行、SHA256 c4d2324941d2fc8934d1b2b56d41e29ca1a9fda34cfa1a764d32116330904d59；本项为 144 行、7e2cee…e44。新增 owner 的保守解码 :46–50、claim :116–117 与 _settle :131–132 的 transport 来源防御均已核对。正常传输 metadata 校验、租约 token/时间/plan 绑定继续保留；本项不重审 task_scripts Lua 目标。
- delivery.py 从第一分项的 122 行、926695…c25 到本项的 137 行、c2fc12…f68，新增严格 source/人工字段/空时间/状态分支；delivery_scripts 从 C2 后的 57 行、f097c2…b2e 到 58 行、47f8bc…68e，新增 owner 终态拒绝。当前完整哈希见下表，不能把 Locke 原报告当作这些新增分支已独立通过。
- worker.py/targets.py/task_scripts.py/plans.py/snapshot.py 哈希与已采用的独立报告相符。本项用 worker 作为实际恢复依赖定位 E1；该发现针对扫描组合，不撤销第一分项的正常 transport 租约/目标结论。
- test_interleavings.py 仅只读核验 A1/A2/A3/B/C 五项固化与 H1-interleavings.md：实际 package/read/create/begin/sent；GET/EVAL 替换、兄弟 CAS、claim 后 TTL、取消活线程晚到/新持有者、实际部分 RPUSH+丢错误响应及永久 started 均有相应断言。277 行与记录 ed8640…5fe 哈希匹配；未复跑，5 passed/8.16s 属于测试实施者，不能转成我的独立运行。
- **P3 / E2 建议：** 后续获准修改测试时，将 probe B 的“Owner 先于 stale ACK EVAL 获胜”及“读取后新加 TTL”固化；当前已有 late ACK 先赢及人工终态后的顺序拒绝，尚未持久覆盖这两个交错。不是另一项 P1/P2，也不要求重跑旧集。

## 本轮独立 probe：实际范围、结果及清理

只执行两个新 stdin probe，命令为 `../.refactor-snapshots/validation-py310/Scripts/python.exe -I -B -`；未保存脚本、未运行任何既有 pytest。初始化关闭 AUTONOMY/PROACTIVE/REDIS_REQUIRED/LLM_REQUIRED，并禁 bytecode。先进入自建空临时目录，禁 Settings 的 env_file；不读取 .env 或真实数据。使用实际 src package、异常类、计划/送达/任务/消费者和 Lua；没有用内存快照或合成 sent 代替实际 read/create/begin/sent。

隔离 Redis 生命周期直接提取既有 test_pending_atomic.py:15–48 fixture AST，仅去装饰器；randomport、INFO process_id=Popen PID 的写前核对、save/appendonly 关闭、Windows 隐藏进程以及 finally close/terminate/wait 保持。AST 提取 recovery 函数正文去装饰器并给其他阶段受控替身，未注册 scheduler、加载真实应用或调用 get_bots；因此实际正文证据不等同完整插件启动。

| Probe | 独立实际结果 |
| --- | --- |
| A，scan/worker 故障组合 | Python 3.10.20 / redis-py 6.4.0 / Redis 5.0.14.1；127.0.0.1:10141，PID 51360。claim/settle 两模式全部反例断言完成并打印；shell 4.445 秒。整体退出码 **1**，原因在断言后：我把 cwd 留在 TemporaryDirectory 内，Windows 阻止其删除并引出清理递归错误。不能报成“probe 全程成功”或绿色测试。Redis 的 fixture finally 已执行；00:04:13 核对 PID 无进程，自建目录 0 子项，以精确绝对路径删除空目录。未重跑该 probe。 |
| B，人工先赢/TTL/反馈 | 同版本；127.0.0.1:11613，PID 5300。人工 sent/abandoned 在 ACK GET/EVAL 之间先赢均保留 raw；claim 在 EVAL 前拒绝；对人工 sent 人为构造同 plan/null 时间的 HistoryLease 检验 finish/defer 的来源防御（这是防御探针，不是真实可授予的租约）。新 TTL 阻止人工写入；已落盘人工 SET 丢响应的 actual history_feedback 报未确认、相同结论保留原操作者/raw。脚本 1.156 秒，shell 2.351 秒，退出码 **0**；finally 恢复 cwd 后临时目录正常清理。 |
| 清理复核 | 00:06:57 查询 PID 51360/5300 均无进程。A 的空临时目录已精确移除，B TemporaryDirectory 正常退出；无额外脚本文件。没有真实 Redis 端口、FLUSHDB、生产 Lua 落盘修改或系统时钟修改。 |

Probe A 的固定 SCAN 页及客户端故障是可控注入；实际 Redis/Python 路径用于确认接口组合，不模拟真实网络中断。Probe B 人工先赢由 EVAL 包装有序安排，验证的是 raw CAS 边界，没有随机调度或生产多进程压力保证。

## 证据归属

- 本 Agent：只读静态/调用关系核对、上述两次新 probe、文件 SHA256 绑定与唯一报告。A 有完整反例输出但清理退出 1，B 退出 0，二者不能折算为 pytest passed 数量。
- 主 Agent / 用户提供记录：入口九项及 ACK 后取消末项 1 passed/3.08s；H1-owner 首轮 9 新+1 原激活 10 passed/13.14s、字段矩阵+2 原查询 3 passed/5.81s、人工 scan 两态/active 不可核对 3 passed/4.24s；3.13 定向 compile 与 diffcheck。只读测试和实现记录相符，未自行复跑，也不将合并运行相加当作独立唯一项数。
- 其他独立评审：foundation snapshot/session-plan/synthesis（含 C1/C2）及 effects 的限定范围结论；读取/采用其当前文件哈希，没有冒充其 Lua、probe 或 pytest 执行。H1-interleavings 首次 5 passed/8.16s 是测试固化者证据，未重新运行。
- 当前只读专属测试：runtime integration（9 个函数）、history discovery（3）、recovery adapter（4 个参数化实例）、reconciliation（6 个实例）、history_owner（2）、manual（6 个实例）；另 interleavings（5）仅核验建议固化。这些计数为源码识别，不是独立收集/执行结果。
- 没有运行旧 6+3、7+8+6、全套、结构扫描、compileall 或 git 全仓 diffcheck；仅检查本报告结构/行尾及绑定文件稳定。Python 3.13 和 3.10 兼容性不因本轮 3.10 probe 扩张为全项目验证。

## 当前实现、只读测试与采用证据 SHA256

17 份本分项生产文件（初读/00:06:57 一致）：

| 文件 | 行数 | SHA256 |
| --- | ---: | --- |
| src/services/chat/history_delivery/runtime.py | 111 | 7545d5d2f4f0a722c1654a55e9cbd617eb98fb78ab4502171dfe6466753a20d2 |
| src/services/chat/history_delivery/discovery.py | 64 | 33c3427caf2df0f561440cf6f3473f10909c02984d1dbb450c0834d7f1009d11 |
| src/services/chat/history_delivery/review.py | 53 | 9a880fbd65a795f9d72411232c4a53a4f52f72073bb7e48ec46a2f0a0c3ebc45 |
| src/services/chat/pipeline/models.py | 57 | 11835f7e3d637351f7099fb99060d91a582262ceec2658a9f78c04620c8d6813 |
| src/services/chat/pipeline/execution.py | 195 | 0c5dbc17a9c6aa5d990d8a09f9a6d83faf0961d947f85f21f8c19b701cf07646 |
| src/services/chat/pipeline/completion.py | 46 | 1e9b8f6809517f46d395baac429253316d5a43ce5829a229ff4d1749b6057e02 |
| src/services/chat/models.py | 46 | 66c2856a36eb5d088b0b3053ed2b3a40c31f8b8679c70714640451feff5ce0ca |
| src/plugins/chat/ingress.py | 82 | bae23a8c0ef01493b26a18a5273e5424e4f0905f9e9d1ccd6be66969a0a434d8 |
| src/plugins/chat/delivery.py | 114 | d3deef857ddcdd2a23d06bf3cb4eb94443884b89049e03ce66e639361781841e |
| src/plugins/chat/recovery.py | 112 | 92507747a5492d3b7be67fe6a6bb51c6dd9b6df68387aed9040b93388ac1fccb |
| src/plugins/autonomy/owner.py | 120 | 516e4cc170f50d46875ed4d2461c6f5505c2dbb8f6683f8e2d7f9d940633b234 |
| src/plugins/autonomy/delivery_owner.py | 102 | bc5421203e5ce4c74fe24ec9feb385b620d323ea82cb5eb946bd3e170c0e5bdd |
| src/plugins/autonomy/history_owner.py | 56 | 733e9ad9e6714038f19e8635800ceb1fe84f61be129ce6d649febb06d9c2d12c |
| src/services/persistence/history_commit/reconciliation.py | 96 | 77a16755a04f3ecba892ea30ef8f637ca8f204861e50ed9ed8f096c6864a5a55 |
| src/services/persistence/history_commit/delivery.py | 137 | c2fc12bfd8e142ac5b6cfef939e5669ebce4d3ebd6fd24c52375338d3f1ccf68 |
| src/services/persistence/history_commit/delivery_scripts.py | 58 | 47f8bc7d1b5001de810ada32bd935fea79ff69b0329fce625add7761e20bc68e |
| src/services/persistence/history_commit/tasks.py | 144 | 7e2cee201060e906806252be637c33aaec3bc4c3c903ffac56801bee78678e44 |

必要已评审依赖（本项不重新验收旧目标）：

| 文件 | 行数 | SHA256 |
| --- | ---: | --- |
| src/services/chat/history_delivery/worker.py | 67 | 4efb3c87c56b2fb6152d4bee2bf77a2a94e0f11781b6755a8f3435202278441f |
| src/services/chat/history_delivery/targets.py | 31 | e962cdbada40e35679ebc0614fcd4cddb62521f5246515725ee1a89f5fc72343 |
| src/services/persistence/history_commit/task_scripts.py | 51 | 6f3053c4e3987a52b4e5c786af5bf6b05dcd08b25d939c660b9786837801da38 |
| src/services/persistence/history_commit/plans.py | 117 | e3387048a3c495ce70599c43be9d6122eecf56b41ee518ba7c8e34f721c455c1 |
| src/services/persistence/history_commit/snapshot.py | 79 | 11da116fb9bd56ac45879e1c49bd7c8d1c12f41d5fed48c4c77ec51ffb01a5a3 |

只读测试与隔离辅助（均未复跑）：

| 文件 | 行数 | SHA256 |
| --- | ---: | --- |
| test/chat/history_delivery/test_runtime_integration.py | 250 | 548bd10e44048fd13fc0f8375a924816967c392035e91a237f849e65bff8dac1 |
| test/chat/history_delivery/test_history_discovery.py | 68 | e6c26cc7ab5f136e81d5c963a0e47c831271086a5b815a8549c3d52d743394a3 |
| test/delivery/recovery/test_recovery_adapter.py | 99 | 183803d7b3e9b31c247370c4bc49a6d5a10c8fd52afa1855db257ba3d2034b68 |
| test/persistence/history_commit/test_reconciliation.py | 123 | 51ff6b6ceae4ce3cdd60c36318b32c70dce54f4b6bbd637e52558a5e0b0734a2 |
| test/autonomy/history_review/test_history_owner.py | 70 | da58bc6b3ba38aac7b576a3642de6246243a986f6ae2dfdb66f76faa9fb33d99 |
| test/autonomy/history_review/test_manual.py | 100 | 93bb8668a8ffcb3296d143f77d74568b28782b0f23a657c3766a78ed4d101a92 |
| test/persistence/history_commit/test_interleavings.py | 277 | ed8640d313e716b68e196a9c756c6f4496aee8f1eb5e1d9ae307a91d841825fe |
| test/autonomy/test_pending_atomic.py | 80 | d9720f49df142b9414423dcf3a90ccc463fa6d74fc78c9fd9aec67e2a2751d6c |
| test/autonomy/owner_loader.py | 18 | a05a7c54a9c0d432d121578fa91747126ed4fe9cc0fef07a63169c05f766ddde |

采用报告/实施说明（属于各自作者的证据）：

| 文件 | 行数 | SHA256 |
| --- | ---: | --- |
| docs/refactor/records/review/resumed/history/effects.md | 84 | fb764a2761baf790e3ba3fc2c846259cca0203cc3bab3c4df63d885bc1ca96a7 |
| docs/refactor/records/review/resumed/history/snapshot.md | 60 | 74a7bfadf8e2746b6920364357b3898e0f371c76b699f5b87d9d4238561de43d |
| docs/refactor/records/review/resumed/history/session-plan.md | 77 | 78ab85baab3e594aafaa738a5840c0229f684996b3cd3b6a663d25782cb04e35 |
| docs/refactor/records/review/resumed/history/synthesis.md | 107 | b422f6dafccf0e56e9cab775e1dd65380a0c7897cfe0b4261bb100d31bde2c86 |
| docs/refactor/records/chat/history/H1-owner.md | 17 | d1bf12d6b19a22ed8c2bac760e177ab4d9b9b5b0aa087d95ebb7c7f33eb99eb7 |
| docs/refactor/records/chat/history/H1d.md | 28 | b731c9f26dc8a630bf0adbaf4a32113b030f89dda4eb14bfd7c9e1af7f63a49a |
| docs/refactor/records/chat/history/H1-interleavings.md | 79 | 770653a9c3c81abf88442cab90fcd7d26ff3657bfa115a39f04197e487e07364 |

## 不能证明的事项与交付

- 当前主回复集成测试使用合成 generate、matcher/QQ ACK，不能证明真实 provider 输入、OneBot/NapCat 实际 ACK 语义、用户收到消息或 QQ 自然度。本轮没有应用、QQ 或收费模型运行。
- ACK 内存时间未落盘时崩溃、重复取消、分类/ACK 遇 CAS changed 后的全路径收尾、Redis 崩溃/复制/资源耗尽/驱逐/删除、Cluster/Hiredis、SCAN 并发变化及大库恢复时延没有独立完整证明；不得猜 ACK 时间或清除永久证据重发。旧快照 ABA/永久回执前提沿 foundation/effects 原限制保留。
- E1 必须修复并定向核验；E2 为固化建议。报告的“未发现其他 P1/P2”不等同完整 H1 通过；后续单独综合 Agent 才能评估跨分项并安排修复。
- 唯一持久改动为本报告；代码、测试和其他文档只读，没有提交/推送/部署，没有秘密/私人数据读取。回退仅移除本报告，禁止撤销主 Agent/其他 Agent 工作或删除 Redis 证据。

交付复核：2026-10-06 00:12:01 +08:00，上表 38 份实现/只读测试/辅助/采用报告的 SHA256 全部保持；追加此句前本报告 148 行、0 行尾空白，审查目录 5 个直属文件。PID 51360/5300 均无进程，A 的精确临时目录不存在。仅做本报告局部复核，没有复跑测试或重新做全仓审查。E1 未修复，保持本分项暂不通过，交后续单独综合 Agent 评估。
