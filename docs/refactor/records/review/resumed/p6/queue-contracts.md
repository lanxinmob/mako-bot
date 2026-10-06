# P6 队列生产、重试与 sent 迁移契约（只读设计评审）

## 开工与证据边界

- 读取时间：2026-09-26，六文档重读后核对时钟为 11:16:51+08:00，随后代码核对至 11:20；模块 P6。
- 工作区：`D:/vscode workplace/fun/bot/mako-bot-refactor`；HEAD `8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9`。当前未提交实现不等于 HEAD 基线。
- 已重读 AGENTS.md、docs/agent/project.md、development.md、docs/refactor/plan.md、modules.md、status.md；`rg --files -g AGENTS.md` 仅发现根说明，无下级覆盖。
- 批准依据：本次用户明确 P1–P6 已批准；status.md 的“2026-09-24 三项方案批准”；records/chat/B3.md:157–175，尤其第 162 行 P6 原子送达/任务与目标幂等约束。
- 唯一写路径为本文；未修改业务代码、原 mako-bot、状态总表、配置或测试；不提交、部署，不连接真实 QQ/生产 Redis。
- 保留：原 action_id/冻结正文/revision/token、unknown 禁止重发、旧版本完成不改新源、Owner 私聊鉴权、手动资讯与定时期次分离。
- 验证范围：静态调用链、Lua 分支、相关现有测试断言、文档格式和行数。本轮没有运行 pytest、Redis 或应用；本文不是实现验收。
- 主 Agent 独立设计目标幂等仓库；本文只定义它必须交付的消费接口，不代其选择历史/费用仓库实现。

## 给综合评审的直接结论

建议批准范围内采用**动作记录内嵌有限个 effect 任务**：发送前冻结计划，普通 ACK 或人工 sent 在同一次最终 SET 中激活任务；后台扫描动作记录、逐 effect 租约认领，调用目标仓库原子幂等接口，再 CAS 确认结果。
不必先建独立队列 hash/zset。现有动作记录已有无 TTL 的稳定地址和分页机制，足以作为最小持久待办；扫描只负责发现，不授权发送或补记。
这满足 sent 与任务同一次原子写入，并避开“先写 sent，再入队”崩溃窗口。若将来增加索引，索引只作可重建加速缓存，内嵌任务仍是事实来源。
当前实现不具备这一保证；下列接口和状态都是建议，尚未接线。

## 当前事实与必须堵住的漏洞

| 证据 | 当前行为 | P6 接线要求 |
| --- | --- | --- |
| state/scripts.py:25–28,35–50,91–95 | 普通 sent、人工 sent 都只写 effects_state=pending；没有任务负载或 effect_id | 两个生产入口必须共用激活函数，同一次 SET 保存完整任务与 sent |
| state/scripts.py:43–44,92 | already_reconciled/already_sent 提前返回 | 新记录重复调用不得重新置 pending；缺计划旧记录必须走迁移分类，不能凭提前返回宣称已入队 |
| state/attempt.py:39–49 | ACK 与持久化确认分离；mark_sent 异常仅告警 | ACK 返回值保留；未确认 sent 时不得直接执行业务补记，不得再调用传输 |
| periodic.py:73–88 | ACK 后直接写去重、历史、资讯指纹 | 全部替换为同一 effect 消费接口；不能同时保留旧直写和新 worker |
| followups.py:55–69 | ACK 后直接去重、complete(snapshot)，两项独立尝试 | 冻结完成条件；重试不使用重新 load 得到的新版本 |
| reminder_delivery.py:72–81 | ACK 后 complete(snapshot, action_key) | 改由任务消费；仍验证原 sent 动作、revision、正文摘要与 bot |
| state/models.py:15–57 | spec 只含正文/源摘要，没有补记计划；action_id 不含正文，digest 包含全部 spec 字段 | effect 计划单独存 envelope，不为加字段重算已有 spec digest 或动作 ID |
| state/recovery.py:25–26；chat/recovery.py | P5 只恢复 queued/rejected 且要求 bot、功能开关、有效期 | P6 不能复用发送 recover 执行补记；sent 即使跨日、bot 离线仍需收尾 |
| followups.py 的源仓库 load/complete；reminder_state 的 complete | 完成后源可能消失或不再出现在待办查询中 | worker 必须从动作记录取任务，不能从 due 索引发现补记 |

静态可确认的核心缺口：任何直写成功后进程退出，动作仍为 pending；后来加入 worker 会再次追加历史/去重。直写失败或取消又没有持久任务来恢复。这不是测试已证明安全的链路。
现有 test_store.py 有 lost_sent_response、cancelled_begin_thread；test_delivery_reconciliation.py 有重复人工结论、竞争、响应丢失，但未断言任务内容或 effect 重放。
现有 test_periodic.py 的指纹失败用例只验证不重发、历史尝试过；不能证明补记最终完成。

## 最小模块边界与接口

`delivery/state/` 当前 9 个直属文件，不向其中连续塞多个 worker 文件；建议新增 `delivery/effects/` 子包。
初始可用 models.py、plans.py、store.py、scripts.py、worker.py 和 __init__.py；按职责划分，不需要通用消息总线或任意回调注册框架。
state/scripts.py 继续维护发送状态转换，并复用一个小的 Lua 激活函数；effect 认领/确认使用独立脚本，但均读取并更新同一动作 key。
plans.py 从已冻结 spec 和原源快照构造明确类型计划；不可持久化 Python lambda、导入路径或任意 Redis key 指令。

建议交接签名（内部接口草案，不表示已存在）：

```text
claim(spec, effect_plan) / recover(spec, effect_plan)
mark_sent(action_id, token)                 # 从已存计划激活，不接临时回调
reconcile(action_id, delivered, operator_id) # 同一激活逻辑
effects.inspect(action_id)                 # 显式效果状态，不复用发送 token
effects.claim(action_id, effect_id) -> lease + frozen_task
target.apply_once(effect_id, payload_digest, frozen_payload) -> EffectResult
effects.finish(action_id, effect_id, lease_token, result)
effects.defer(action_id, effect_id, lease_token, reason)
worker.run_page(cursor, limit=3) -> next_cursor, outcomes
```

目标仓库结果至少区分：`applied`、`already_applied`、`superseded`、`unavailable`、`conflict`。
只有前两项能声称业务写入成功；superseded 表示旧源已被修改/删除、无需且不得应用，单列终态，不能称为已写入。
unavailable 包含写前失败与写后响应丢失；只有幂等已保证的目标允许重试。conflict 为同 effect_id 不同负载或坏数据，隔离待核对。
普通 bool/None 或“方法正常返回”不足以充当持久化凭证。目标原子去重标记必须和业务变更一起落库，不得先 SETNX 再调用旧仓库。

## 冻结计划与同一次原子写入

建议保留 schema_version=1 的现有 spec_json，另加有版本的 effect envelope：

```text
effects_version: 1
plan_digest: hash(canonical_plan)
effects: [{effect_id, kind, payload_digest, payload,
           state, attempts, lease_token, lease_until_ms, next_attempt_at_ms,
           result_code}]
sent_recorded_at_ms: Redis TIME（首次 sent 写入时固定）
confirmation_source: transport | owner
effects_state: not_started | pending | complete | needs_review
```

- effect_id 建议为 hash([action_id, 稳定语义名, occurrence])；本三类每种只有一次，occurrence 固定 0。不要包含重试次数、随机 UUID、租约 token、执行时间；实现升级不能重新生成 ID 后重做历史效果。
- payload_digest 独立绑定业务负载。金额、用户、原费用日期、正文、目标、源版本、指纹集合、去重归一化结果等一经冻结不得在重试中改写。
- 发送前计划中的时间字段可声明为“首次 sent 记录时间”；activate 时一次性填入 Redis 时间并固定最终 payload_digest。plan_digest 绑定模板，payload_digest 绑定已实例化任务，不能在 worker 中补当前时间或重新算一份不同负载。
- 新动作 claim 前构造并完整校验计划，claim 同时保存 spec 和 dormant/not_started 任务；claim/begin 均保留原源校验。
- 已有 queued/rejected 的原 spec 必须保留；有匹配原源证据时可在 begin 前 CAS 安装计划。无计划不外发；不得拿当前新源替换旧计划。
- begin 原子核对计划版本/摘要可识别且齐全；lease 回收只更换发送 token，不清空计划、效果 ID 或冻结负载。
- 普通 sent 保留同 token、sending/unknown 准入；人工 sent 保留同 digest、unknown 准入。二者调用相同 activate_effects，首次固定确认时间和确认来源，把 dormant 改为 pending。
- 在写任何字段前验证整条动作和全部任务的类型、数量、负载与结果；先在 Lua 内存中完成转换及 cjson.encode，最后一次 SET 保存 sent 与激活后的任务。
- 当前脚本顶部会先将过期 sending 保存为 unknown；可以保留该保守状态转换，但最终 sent 与任务不能分两次写。不要将 Lua 无交错解释成任意运行时错误都会回滚。
- 合法的新 sent 重复 mark/reconcile 返回原计划和原结果，不重置已完成 effect、不延长时间、不覆盖首位核对者。空计划仅允许明确没有持久效果的种类；本三类不允许漏任务伪装为空。
- 不给动作/任务增加短 TTL；目标去重凭据保留期至少覆盖任务仍可重试的全部时间。当前不设计自动清理。

## 三类生产者的精确负载

| 入口 | 必需 effect | 冻结输入与约束 |
| --- | --- | --- |
| PeriodicDelivery | outbound_dedup、global_history；指纹非空再加 news_fingerprints | 必须来自 claim 返回的 frozen.payload，而非本轮重新抓取的 text/fingerprints/intent；source 为原 business_id，group/bot 为原目标 |
| FollowupDelivery | outbound_dedup、followup_complete | 文本为 spec.payload；intent=reminder，source=relationship.followup；完成绑定 user/memory/revision/source_digest，传原 snapshot 或由目标仓库在 Lua 内验证摘要后更新 |
| ReminderDelivery | reminder_complete | 原 job_id/revision/source_digest、action_key、bot/目标；只清匹配源及调度意图，保留动作证据 |

跟进原 `complete(snapshot)` 需要 raw 与模型；提醒原 complete 需要 raw/revision。不能从发送文本反推完整业务源，也不能完成前调用 FollowupSource.load（完成后 due 已消失，且 load 有旧项隔离副作用）。
最小适配二选一由主 Agent 与综合评审收敛：在计划内冻结必要源快照；或目标仓库接收冻结 digest/revision，在原子操作中读取当前 raw、验证身份和摘要，再产生有限字段更新。后者无需复制完整业务源，但必须能识别已完成凭据。
本三条现有送达后路径没有 consume_cost 调用，不新造“发送费用”。若主 Agent 提供费用幂等 API，本轮队列仅预留明确类型；其他生成/自主入口生产费用任务需单独核对其已批准范围，禁止按送达次数重复记生成费用。
历史时间、去重 created_at、指纹 sent_at 不能在每次重试使用 datetime.now()；新自动 sent 可固定首次确认入库时间，并明确它是记录时间，不承诺精确传输时刻。人工 sent 没有可靠实际送达时间，见下文保守规则。
指纹多项可视为一个原子批任务；若目标仓库只能逐项写，则每项独立稳定 effect_id，不允许一部分成功却整批重试非幂等操作。
窗口观察 observe_group_output 是进程内最佳努力，不加持久任务、不在重试时向群窗口重灌旧消息。

## 重试、取消和并发

1. 用独立分页游标扫描动作 key；只选择 state=sent 且受支持的 pending/retry_wait 效果。unknown、cancelled 不消费，P5 发送 recovery 仍不接受 sent。
2. Redis TIME 计算 effect 租约；claim 在同 key Lua 中重新检查 sent、effect_id、payload_digest、next_attempt_at_ms 与旧租约，生成与发送 token 无关的新 lease_token。
3. worker 把冻结任务交给 `apply_once`。目标必须在一个原子操作内校验 effect_id+digest 并执行业务变更；多个 worker 重放仍只应用一次。
4. applied/already_applied 后以 lease_token+payload_digest CAS finish。只有所有任务均有明确终态才结束待办；含 superseded 的汇总必须保留“未应用旧版本”原因。
5. 写后响应丢失保留 pending/leased，租约到期可重试同 effect_id。效果写成功但 finish 丢失亦同；旧 worker finish/defer 被新租约 fence，不能回滚新结果。
6. `to_thread` await 被取消不代表线程停止。退出时不释放租约、不确认成功、不生成新 ID；让租约到期后通过幂等仓库恢复。不得吞 CancelledError 后继续循环。
7. unavailable 使用有上限退避与有界每页工作量；失败不删除，不把其他 effect 阻塞。conflict/不支持类型进 needs_review；长期故障保留记录并告警，不自动认定完成。
8. 发现扫描可重复、空页且非末页，COUNT 不是硬大小上限；沿用分页 offset 防止稳定键空间丢尾项。每轮返回末尾后从 0:0 开新轮，不能永久跳过失败项。
9. 不按 spec.valid_until_ms、今天日期、默认群变更或 bot 在线状态丢弃已送达补记；原目标不会因为配置变化而被重定向。P6 worker 只接存储，不持有 bot 或 dispatch。

ACK 已明确但 mark_sent 未确认：保留 acknowledged=True/state_confirmed=False 的区别。进程尚存时可对同 action/token 重试幂等 mark_sent 或重读，绝不再调用发送 callback；应有界并保留未确认反馈。
进程在网络 ACK 与 sent 落库之间崩溃仍有不可消除的窗口：重启看到 unknown 不得推定成功，由 Owner 核对。原子任务只能保证 sent 一旦持久化就带任务，不能消除外部网络结果未知。
原 ACK 后直写必须在启用该动作的新计划时一并替换，立即补记若保留，也只能调用相同 worker/目标幂等接口，不能绕过任务认领。

## 人工 sent 与晚 ACK

- 不改变现有 Owner 私聊鉴权、同 digest 二次校验、仅 unknown 可人工终结；未过期 sending 拒绝、同结论幂等、冲突终态拒绝。
- 有可信发送前计划的新 unknown：人工 sent 同一次 SET 激活计划并固定 operator/time/source=owner；不要在命令处理器返回后另 enqueue。
- 人工 cancelled 不激活任务，晚 ACK 不能覆盖它；人工 sent 后晚 ACK 不再重置任务、不覆盖人工记录时间，也不重新生产效果。
- 没有可信计划的旧 unknown：仍允许记录 Owner 的送达事实，但同次写入 legacy_review 任务/needs_review 标记；不得将“人工知道送达”推导成“旧历史肯定未写”。
- 人工确认只有核对时间，缺少实际送达时间。完成 CAS 可按原版本安全收尾；历史/去重/指纹若会把核对时间当发送时间，应先进入 needs_review，不能默默延长冷却或重写排序。允许如何补实际时间/接受核对时间替代属于待确认政策。
- 反馈继续明确“已送达不表示补记全部完成”；不得为了 worker 接线默认通知第三方或增加真实消息。

## 已有 sent 的迁移矩阵

`effects_state=pending` 对旧版本没有缺失效果清单含义；现有发送器即使直写全部成功也不会更新它。因此不能自动给所有旧 sent 配新 effect_id 再执行旧仓库。

| 旧记录情况 | 默认迁移动作 | 自动消费资格 |
| --- | --- | --- |
| 新版本已带完整任务 | 不迁移；重读状态后按稳定 ID 续跑 | 目标幂等接口满足契约才允许 |
| 旧 sent，无计划/凭据 | 同 key CAS 添加版本化 legacy_review 标记，保留 sent、原 spec、原 token；只作分类 | 默认不重放追加历史、扣费、去重日志 |
| 旧 reminder sent，存在相同 action_key/revision 的完成墓碑 | 原子核对后记已存在完成证据 | 只终结该 completion；不推出其他效果成功 |
| 旧 reminder/followup sent，当前源仍匹配冻结 revision/digest | 可以生成版本受限 completion 候选，目标仓库验证原 sent 与源 | 仅目标提供原子证据/幂等语义后；不可凭本地读取结果直接更新 |
| 原源已删除/替换或缺失 | 保留送达记录，completion 分类 missing/superseded/needs_review | 不重建旧源、不触碰新版本；无证据不得声称已完成 |
| 旧周期 sent，有冻结正文/指纹，无效果凭据 | 可恢复意图清单，不能恢复已执行与否 | 历史/去重默认 needs_review；指纹也不得盲目刷新 sent_at |
| 旧记录坏 JSON、spec 不符、未知 kind/version | 原样隔离并报告有限原因 | 禁止消费；不自动修成 queued 或缺失记录 |

跟进源当前 status=done 仅能说明业务已完成，不证明某 effect_id 执行过；旧实现的 done 幂等分支还依赖同 revision。不得当成历史/费用凭证。
ReminderStateStore 的 already_completed 有 action_key+revision 墓碑，可作为较强的完成证据；不能将通用 missing 等同 already_completed。
迁移必须有界、可重复，以原记录摘要/版本 CAS；与正在运行的 mark_sent、reconcile、effect finish 竞争时重读，不覆盖新任务状态。
不靠时间戳切分新旧安全性，以计划版本和证据判断。旧发送进程仍运行会产生无凭据直写：实际切换前必须停/排空旧发送与旧补记进程，再启用新协议。本文不执行停机或部署。
不能保证旧记录不存在重复时，不以“更少漏记”为理由批量重放；批量补历史、历史费用、清理/归档和丢弃记录均需具体数据方案与授权。

## 已授权与仍需确认

**P6 已授权的实施方向（本轮仍只写设计）**：送达/任务原子保存；稳定 effect_id；目标原子去重后才重试；取消/响应丢失安全；三类现有效果改走任务；有界补记扫描；只读分类旧 sent、保守保留无法证明的效果。
内嵌计划、独立 effect 租约、typed result、子包划分属于上述范围内的最小实现建议，无须重复索要 P6 授权；仍须主 Agent 与第三位评审核对目标仓库接口后接线。

**需要进一步明确的政策/扩展，默认不实施**：

- 人工 sent 的实际时间缺失时，是否接受核对时间作为历史/冷却/指纹时间；若需要新 Owner 参数或命令，需说明接口变化。
- 无凭据旧历史/费用/去重的批量重放、推断为已完成、跳过或清理策略；默认 needs_review，不做不可证明的迁移。
- 超出本三类生产者的 B1 自主/聊天生成费用接入、自动消息通知、新配置项、生产迁移/部署；不由本评审扩大范围。
- 若另选独立 Redis 队列、多 key 事务或 Redis Cluster 支持，需重新核对键槽、索引修复与失败原子性；不把本单 key 结论直接搬过去。

## 第三位综合评审的阻断检查与定向验收

接线前需主 Agent 交付：每种 effect 的 apply_once 签名与原子返回值、去重凭据保留期、历史/时间/费用日期策略、完成 CAS 的 missing/superseded 分类。缺任一项，不启用该 effect 自动重试。

建议只运行与以下风险对应的受控测试；本轮均未运行：

| 场景 | 必须断言 |
| --- | --- |
| sent 普通 ACK/人工两入口；任务负载坏数据 | 同次读只看到旧状态或 sent+完整任务；错误不得出现 sent 无任务 |
| SET 已写后响应丢失；重复 mark/reconcile | 同 effect_id、原负载/时间不变，任务不重复生成，传输不重试 |
| worker 写后断连、finish 断连、取消后线程迟到、双进程租约竞争 | 目标业务效果一次，旧 token 不覆盖新状态 |
| 三类实际入口，ACK 后立即取消/崩溃 | 有 sent 就能扫描到任务；没有 sent 不绕过未知状态消费 |
| 两个效果一成功一失败；completion 返回 changed/missing | 独立推进，旧源不被复活，新版本不被完成 |
| 跨日/功能关闭/bot 离线/默认群变化 | 不重发、不转目标；既有 sent 效果仍可按冻结信息收尾 |
| 人工 sent 与晚 ACK/人工 cancelled 竞争 | 首个终态及核对元数据保留，无重复任务 |
| 旧 sent 其实已直写历史、无幂等标记 | 不再次 append/consume；归入待核对 |
| 旧提醒完成墓碑、旧源修改/删除、旧周期指纹时间 | 分类准确、CAS 不误伤，迁移重跑无重复 |
| 混合旧/新/坏记录分页、扫描重复/空非末页 | 有界、失败保留、恢复扫描不调用发送器 |

测试应延续现有 test/delivery/state 的发送/人工核对断言，新增 effects 子目录避免 state 测试目录继续拥挤。若做 Lua 动态验证仅使用隔离合成 Redis；不能以 Python 替身证明 Lua 原子性。
回退：本文仅为设计，可撤销本文；未来实现回退须先停效果 worker 和相关发送器并保留任务/去重凭据，不能恢复不认识任务的旧直写路径。

## 快照与交付状态

关键源码 SHA256（本轮只读快照，便于主 Agent 并行变化后判断结论是否仍适用）：

| 文件（src/services/delivery/ 下） | SHA256 |
| --- | --- |
| state/scripts.py | FCED81D69DB17EE93B5E2E9A4FE730D9F11B120F6BF37D1CFE4B96621A13DD0F |
| state/store.py | 0147B30766BD04BFD6DE6CD0EF9BC1CB253C5B57E229294640CC38E78F98C076 |
| state/attempt.py | 3739964B81C2F09FC42E02479BD486954E98AA913EC84765ABC02C8A0EBE5971 |
| periodic.py | 90829F474D4B0F133762E4BA5164D5B6F234AF02B709880C218391287D6DDF37 |
| followups.py | 4927EF1B0A1C6BD94DF64C4BF3F8DE793F8BF2955E08705F7F08B960BA27C3CD |
| reminder_delivery.py | B941D91DBCE4D24568A2557C833A0E437BB39E1F5FDD74811B2D15C41D3B6254 |

本工作单元完成的是队列接入契约与缺口评审。P6 代码、目标仓库整合、动态故障验证和第三位综合评审仍未完成，不将建议当完成。
本地检查：本文小于 400 物理行，仅此路径新增；未跟踪文件另做尾随空白/冲突标记检查，不把 git diff --check 对未跟踪文件无输出当成正文校验。
