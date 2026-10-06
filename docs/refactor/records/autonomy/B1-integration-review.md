# B1 独立方案与接入设计审查

## 开工、授权与结论

- 重读时间：2026-09-16 11:43–11:48 +08:00；模块 B1。
- 工作区：`D:/vscode workplace/fun/bot/mako-bot-refactor`；HEAD `8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9`。工作区已有未提交功能改动，本审查以读到的文件为依据，不以 HEAD 冒充当前实现。
- 已重读六文档：根 `AGENTS.md`、`docs/agent/project.md`、`docs/agent/development.md`、`docs/refactor/plan.md`、`docs/refactor/modules.md`、`docs/refactor/status.md`；`rg --files -g AGENTS.md` 仅发现根说明。
- 已读 `B1-proposal.md`。用户本轮和 status 的 2026-09-16 追加记录已批准 Redis 持久化、故障时保留待办并暂停审批发送；提案标题“待开发者决定”属于未更新文字，不要求再次批准。
- 本任务唯一允许写入路径为本文件；指定四份代码及辅助解析/注册代码只读。storage worker 并行产物不在本报告验收范围内。
- 保留契约：自动行动仍走 autonomous；Owner 批准走 command 有界排队；白名单、冷却、语义去重、治理、预算仍在发送前复核；已确认发送与补记失败分离；Python 3.10/3.13；config.py 不拆分。

**结论：批准方案的方向可接入，但当前四文件尚未满足 B1。下述契约应作为存储与编排合并条件；本报告完成独立设计审查，不等于新实现或 Redis 原子性验收通过。** 最小方案可保留 dispatcher 的公共 bool 接口，在审批编排中增加认领状态与传输阶段记录，避免迫使所有发送调用方迁移。

## 当前代码证据与问题

行号为本次读取快照，后续并行修改应按函数定位。

| 级别 | 证据 | 必须补齐的行为 |
| --- | --- | --- |
| P1 | `owner.py:46–69` 在 load_latest_pending 后直接 await send_action，成功才删除 | 双批准可读到同一 pending；必须先原子认领，失败者不能排队或发送 |
| P1 | `owner.py:53–57` 取消仅 delete_pending；`execution.py:118–129` guard 不读执行状态 | queued 取消必须与进入 sending 竞争同一原子状态转换，不能只删除正文 |
| P1 | `dispatcher.py:139–168` guard 拒绝与 API 异常都返回 False；`execution.py:137–144` 统一解释未确认 | False 不能授权重试；必须区分未进入传输和发送结果未知 |
| P1 | `repository.py:107–154` pending 读写异常回退内存 | 审批强一致路径不得使用 fallback；缺失、冲突、存储不可用必须是不同结果 |
| P1 | `repository.py:144–150` GET latest 后 DELETE | 旧清理可删除并发新建的 latest；比较与删除必须放在同一 Lua 原子操作 |
| P2 | `owner.py:14–23` 仅有 latest pending 才接管普通审批；`parsing.py:approval_command` 无 ID 核对命令 | unknown 必须在 pending 到期、latest 被替换后仍可按 ID 查询和终结 |
| P2 | `execution.py:64` 对内容 align_time_greeting；Owner 支持 replacement | 摘要必须绑定批准后实际发送内容，不能只散列旧 pending.message |
| P2 | `execution.py:16–17` 以 UUID 前 8 位生成 pending_id | “旧 ID 不复用”不能仅依赖短随机值；创建应防覆盖，且执行墓碑存在时拒绝复用 |

`_record_sent_action` 已独立尝试冷却、去重、费用、历史和审计，不应在 B1 改回“任何补记失败就发送失败”。其成功调用也不等于持久化成功。

## 存储单元与编排单元的最小契约

下表是语义接口建议，不宣称 worker 已实现这些方法名。存储单元提供原子动作，编排单元负责生命周期及用户反馈。

| 动作 | 原子输入与条件 | 返回语义 |
| --- | --- | --- |
| claim | 明确 pending_id、pending 原始版本/摘要、最终批准内容摘要、目标、唯一 token；pending 未到期；无执行记录、rejected_before_send 或过期 queued | claimed / busy / terminal / missing_or_expired / mismatch；Redis 不可用单独报错 |
| begin_send | ID、token、批准摘要、目标；仍 queued、租约有效、pending 有效且原始版本未变 | 仅成功 CAS 为 sending 才授权本次一次传输；其余一律不外发 |
| reject_queued | ID、token；仍 queued | 转 rejected_before_send；不删除别人的 token，不覆盖 cancelled/sending |
| cancel | ID；检查执行状态并与 queued→sending 互斥；无执行记录时也需核对有效 pending | 无状态或 queued→cancelled；sending/unknown 返回不可保证撤回；sent 返回已送达 |
| finish | ID、token、预期状态/版本 | sending→sent 或 unknown；旧 token、人工终结后的迟到回调不可覆盖终态 |
| inspect / reconcile | 明确 ID；不依赖 pending/latest；核对状态版本与人工操作身份 | 返回实际状态；人工核对仅终结不外发 |
| cleanup | ID、已允许清理的执行状态 | 删除对应 pending；仅 latest==ID 才删除 latest；保留执行证据 |

执行记录沿用提案字段，补充明确的 queued 租约截止时间（或可可靠推导的租约语义）、状态版本和人工处理原因/时间。租约建议使用 Redis 统一时间来源，不能用各进程 monotonic 值跨实例比较。queued 租约失效只能令旧 token 失权，不能删除整个执行记录来表达租约到期。

claim 同时检查 Redis 中 pending 与执行状态。不能先由 fallback 读到 pending，再只对执行 key SET NX。未知 schema、损坏载荷或状态不可读均关闭审批出口；禁止解释成“没有状态”。claim/begin_send 超时可能已经在服务端成功，不可改用内存或换 token 盲重试发送。

审批正文保留 PendingAction JSON。对“改成 xxx”，先完成本地内容规范化与渲染准备，构造不可变批准快照；快照至少含 ID、target_type、target_id、intent、最终文本。执行记录仅存其摘要和原 pending 版本摘要，不复制私人正文。发送使用同一快照，排队后不得重新对问候语或替换文本做变化；如果必须重算导致摘要不同，拒绝当前尝试并要求重新明确批准。

`save_pending` 当前有两次独立 SET，第一步成功第二步失败会形成部分保存。B1 的审批必须以 Redis 实际有效 pending 为准；内存待办可保留但反馈为持久化未确认、暂不可审批。不得将两次 SET 均失败后的内存副本自动当成可执行记录。创建应避免覆盖旧 ID；通知应包含 ID，便于 latest 未更新时定位。

## 发送最小接入与阶段边界

1. Owner 路由做鉴权，选定明确 pending_id，读取快照并调用 claim；只有 claimed 的 token 才进入执行。普通“批准/取消/改成”可保留 latest 简写，但解析一次后全程绑定该 ID，不在 await 后重读 latest 来决定清理对象。
2. 保留现有本地预检。预检失败以及 dispatcher 队满、目标容量限制、排队截止前未获槽位，均通过 token 匹配的 reject_queued 结束；只有明确未进入 sending 才可在下次显式批准时重新认领。
3. dispatcher guard 先复核原有权限/冷却/去重/治理/预算；最后一步调用 begin_send。它是取消与发送的线性化点：取消先成功，guard 必须失败；begin_send 先成功，取消只能提示可能已送达。guard 成功后不再进行可失败的内容生成、渲染或其他业务 await。
4. send callback 只执行一次适配器调用。审批编排维护本次尝试的阶段：queued、boundary_uncertain、sending、api_started、acknowledged。begin_send 调用前进入 boundary_uncertain，只有明确拒绝才能恢复为未进入边界；存储异常不得回退到 queued 推断。
5. 适配器成功返回且结果不是 False 时，callback 立即记录 acknowledged；再由编排持久化 sent，随后才清理 pending 和调用补记。即便外层调度取消，callback 已记录的 acknowledged 也不能被覆盖成未发送。
6. 向 Owner 返回结构化结果（例如状态、原因、delivery_confirmed、state_persisted），不要继续仅用 send_action 的 bool 判断可否重试。可为审批新增专用编排入口并复用发送策略，保留自动发送的现有 bool 契约。

以上可不修改 dispatcher：通过 guard、send callback 和外层 try/except/finally 完成。不要向 dispatcher 塞 Redis、Owner 或 pending 领域知识。如果后续采用通用结构化 dispatch API，需另保留 bool 包装兼容现有调用方；B1 不要求全发送链路迁移。

## queued 取消、sending 未知与 API 超时/取消

| 发生位置 | 持久化动作 | 反馈与可重试性 |
| --- | --- | --- |
| 排队中 Owner 取消 | 原子 queued→cancelled；清理 pending 使用同一 ID | “已取消，尚未进入发送”；旧回调随后 guard 被拒，不自动重发 |
| 排队任务 CancelledError / 超时 | 仅 token 匹配且仍 queued 时转 rejected_before_send | 未进入外发，可在有效期内再次显式批准；不是自动重试 |
| begin_send 写入报错、响应丢失或 guard 超时 | 无肯定授权就不调用 API；保留可能已写入的 sending | “状态未确认，暂停执行”；恢复后按 ID 查询，不能凭 dispatch=False 释放 |
| 已取得 sending 但 callback 尚未运行即取消/崩溃 | 保留 sending，之后保守归为 unknown | 可能实际未发，但不得自动重新认领；人工核对 |
| 适配器超时、异常、返回 False 或调用中 CancelledError | token 匹配地标 unknown；写入失败保留 sending | 无成功确认不代表未送达；禁止重复批准原 ID |
| API 明确成功，但 sent 写入失败 | 保留本地 acknowledged，Redis 留 sending/unknown；不清除证据 | “已送达，但状态保存未确认，请核对记录”；禁止再次发送 |
| sent 已写，pending 清理或补记失败 | 保留 sent，允许以后仅清理，不重新发送 | “已送达”；失败的是清理/补记 |

`dispatcher.py` 捕获的是 Exception，调用者取消会传播；外层必须显式处理 asyncio.CancelledError、进行有界状态收尾后重新抛出，不能吞取消返回普通 False。发送前预检异常也必须收尾已认领的 queued。不要在 finally 无条件 release/delete。

收尾如需 shield，应保存任务引用且限制等待；不能派生无人管理的后台发送或无界等待。现有 wait_for(send(), send_timeout) 给出取消请求边界，但若适配器吞取消，不能据此承诺硬截止或已撤回。超时路径禁止自动重试；接入测试须覆盖迟到确认和外层取消竞态。

同步 Redis 调用不得无限阻塞事件循环；对存储操作设置有限超时。若卸载到线程，协程取消不会撤销已经开始的 Redis 写，因此必须按 boundary_uncertain 处理，不能通过线程取消宣称操作未发生。

queued 到期可由新 token 认领；旧 token 所有 begin_send/reject/finish 都无权影响新认领。sending 到期只归 unknown，不可抢占发送。unknown、sending 记录不能随 pending TTL 到期自动消失；sent/cancelled 的清理策略也需确保不能让同一 ID 重新执行。

## Owner 人工核对与命令接入

建议最小明确语法如下，作为本次提案中“人工核对指令”的具体接入设计，尚未实现：

- `行动状态 <id>`：显示目标、状态、更新时间及是否需核对；只返回 Owner 有权查看的数据。
- `行动核对 <id> 已送达`：对 unknown（或已确认执行者终止的遗留 sending）原子标 sent，记录来源 owner_reconciled；不调用发送，也不盲目重做费用/历史。
- `行动核对 <id> 放弃`：转 cancelled 并记录 manual_abandon，反馈“已停止后续处理，不能保证此前没有送达”；不宣称撤回。

unknown 的“放弃”和 queued 的“取消”语义不同，需保留原因字段。重复相同核对结果应幂等，冲突核对要求先展示当前状态；比较 state/version，不能 last-write-wins 覆盖新的终态。仍可能运行的 sending 只允许查询和提示，不能因租约过期就声称远端请求停止。人工终结后迟到 callback 不得覆盖终态或再触发副作用，可另记录迟到证据。

核对命令在 owner.autonomy_rule 中应先做 PrivateMessageEvent + is_owner 检查，再按明确语法接管，不依赖 load_latest_pending 或 LLM 判断。即使 autonomy 关闭，状态查询/人工收尾也应可用；关闭时批准/建议仍禁止外发。process_owner_private 入口也宜显式检查身份，避免未来直接调用绕过 rule。

未知记录必须能在 pending 已到期、被清理或 latest 指向其他 ID 时定位。Redis 故障返回“状态暂不可用，未执行核对”，不能回答“没有待办”或“已取消”。Owner 反馈消息失败不改变已完成的原子操作，重复命令按持久化状态回答。

本模块不提供“unknown→queued 重试”捷径。需要再次发送时，另建新 ID 待办，明确提示可能重复并取得新的批准；不得复用旧 token/ID，也不得由“已送达/放弃”命令隐式新建并发送。

## latest compare-delete 与恢复边界

清理逻辑需在一个 Lua 操作内按明确 ID 执行：核对允许清理的状态，删除该 pending；GET latest 等于该 ID 才 DEL latest。若 latest 已是新 ID，原样保留。不能 pipeline 两条命令冒充原子比较，也不能先由 Python 判断再发 DEL。内存缓存清理只移除同 ID，不得影响 Redis 状态判断。

取消建议把状态迁移与 pending/latest 清理放同一脚本；sent 的清理可独立执行，因为 sent 已经阻止重发。清理失败不回退终态。GET 返回 bytes 的处理、空 key、旧 pending 已过期都需有确定语义。

无执行记录的旧 pending 可在首次明确批准时进入新 claim；旧进程已经外发但没有执行记录的动作无法自动辨认。上线/回退必须停止旧审批入口并核对在途操作，不能让旧版本继续忽略 execution key。Redis 数据丢失、故障恢复到陈旧快照也超出本状态机的防重保证；不能宣称 OneBot exactly-once。

## 必要验证与交接

本轮仅做文档和源码静态审查；未导入应用、未运行 pytest、未读取 .env、未连接 Redis/QQ/模型或其他真实服务。以下为实现验收要求，不是本轮通过结果：

| 受控场景 | 必须观察的断言 |
| --- | --- |
| 两个批准同时 claim，同一 ID 不同 replacement | 只有一个 token 获准且 API 最多一次；最终文本与获胜摘要一致 |
| queued 取消与 begin_send 两种先后次序 | 取消胜出 API 为零；sending 胜出不能承诺撤回 |
| 排队截止/任务取消/预检异常 | 只释放本 token 的 queued，不覆盖新 claim/cancelled |
| begin_send 服务端成功但客户端报错 | 不调用 API，不释放为可重试状态 |
| API 超时/取消/失败及成功确认与取消同时发生 | unknown 不重发；已有 acknowledged 不降格成未送达 |
| sent 写失败、cleanup 失败、补记失败 | 外发最多一次，状态/反馈分别准确 |
| queued 租约换 token、sending 租约到期 | 旧 token 无权发送或终结；sending 不可重新认领 |
| pending TTL 过期、latest 更新后人工核对 | 旧 ID 仍可查询/终结，新 latest 不受影响 |
| Redis 不可用、有内存 pending、未知 schema | 审批 API 为零，待办保留，反馈不可用而非不存在 |
| 未授权用户、群消息、autonomy 关闭 | 非 Owner 不可操作；关闭后只允许 Owner 查询/收尾 |
| 旧清理与新 latest 创建交错 | Lua 保留新 latest；已终结状态不因清理失败消失 |

storage worker 应交付确切返回类型、字段、租约规则、状态转移表及 Lua 的隔离 Redis 验证。替身测试不能证明脚本原子性；若暂不能进行隔离 Redis 验证，明确保留该项，不能使用真实服务补验。主 Agent 整合后仅跑上述风险相关测试，再由独立评审检查实际接线。

本报告无需更新 status 或他人文件；仅撤销本文件即可回退本次文档交付。业务实现回退另按上述在途状态处理要求执行，禁止全仓 reset 或清理并行 worker 改动。
