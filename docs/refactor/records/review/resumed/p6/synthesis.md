# P6 第三位独立综合评审与最终接线方案

## 开工、授权与结论

- 日期：2026-09-26，Asia/Shanghai；本轮重读后核对时钟为 16:10:17+08:00。
- 工作区：`D:/vscode workplace/fun/bot/mako-bot-refactor`，评审当前未提交工作树，不以历史 HEAD 代表实现。
- 已重新读取 AGENTS.md、docs/agent/project.md、development.md、docs/refactor/plan.md、modules.md、status.md；`rg --files -g AGENTS.md` 仅发现根说明。
- 输入：本目录 source-contracts.md、queue-contracts.md；实际目标写入器、源完成、发送状态及三类生产者、旧历史/出站仓库与定向测试。
- P6 由用户批准；本工作单元仅独立评审，唯一持久写路径为本文。未修改业务代码、测试、状态总表或其他报告。
- 保留契约：原 action/spec/revision、unknown 不重发、旧源不覆盖新源、Redis 故障不转内存成功、Owner 鉴权、不自动清理历史证据。
- 验证范围：14 项现有窄回归及 5 项内存隔离探针；未运行全套、应用、QQ、生产 Redis、提交或部署。

**结论：采用下述内嵌任务方案继续已批准的 P6；现有目标写入器在已测故障模型下可作为基础，S2 索引修复通过独立复核，但当前 P6 整体尚不通过实现验收。**
源 effect 永久回执、两条 sent 原子激活路径、消费者与三类入口替换、旧数据分类尚未实现；这些是接线验收阻断项，不是重新申请 P6 授权的理由。

用户本轮再次明确批准的人工时间政策作为本方案硬约束：无实际送达时间时，历史/去重/指纹进入 needs_review，源完成按原版本独立收尾；晚到 ACK 不覆盖人工结论。
两份先前报告仍写待确认，已被本轮明确指令取代；不再询问相同政策。16:15 后补充核对了主 Agent 新落地的人工 sent 补丁，结果如下。

## 独立确证及两份报告的处置

| 项目 | 本轮证据 | 综合判定 |
| --- | --- | --- |
| 目标写入器 9 项 | 独立运行 test_effect_targets.py，全数通过 | 确认原结论，限于这些断言覆盖的故障 |
| S2 already-done 漏 ZREM | followups.py:51–58 已先核对 revision 再清索引；指定新增回归独立通过 | 此缺陷关闭；不等于源 effect 回执完成 |
| S1 完成后改源丢失可判定性 | 新探针：complete 成功后 update，再以旧 snapshot complete=False；delete 后也 False；新正文未被覆盖 | 缺口仍在，不能将 False 一律归为 superseded |
| S3 重试依赖旧 snapshot | followups.py:119、reminder_state/store.py:99 仍要求 snapshot；源 load 不是旧快照恢复接口 | 必须新增 effect 级完成入口 |
| 提醒已完成凭据 | reminder_state/scripts.py:33–41 的 already_completed 绑定 action_key/revision；create:78–80 覆盖当前源/意图 | 支持报告的静态结论；本轮未复跑其 8 个历史探针 |
| sent 与任务 | delivery/state/scripts.py 普通 sent 仍仅写 pending；人工 sent 新补丁写 needs_review 及时间来源，均无 effect 清单 | 尚无可靠补记队列，不能把 pending 当作未执行证据 |
| 人工时间政策补丁 | reconcile_sent 同次 save('sent') 写 owner 来源、记录时间、null 实际时间及 actual_delivery_time_unknown；4 项新增范围回归及 1 项 Owner 探针通过 | 本项保护通过；不能将其当作已按任务激活源完成 |
| 实际入口 | periodic.py、delivery/followups.py、reminder_delivery.py 仍 ACK 后调用旧仓库 | 新 worker 启用前必须同批切换，不能双写 |
| 目标永久回执 | effects/store.py:26–43；scripts.py:7–10、52；新探针删除合成目标后重放返回 already_applied、目标不重建 | 回执不依赖业务数据仍存在；不是目标数据永久保留保证 |
| 身份冲突 | 新探针：相同 effect_id 换出站目标被 EffectConflict 拒绝，新目标无写入 | kind/目标/完整载荷摘要绑定有效 |
| 坏资讯值 | 新探针：批次后项已有非法时间，前项无写入、无回执，抛 EffectUnavailable | 写前检查有效；当前错误分类仍将确定性坏数据并入 unavailable |

纠正 queue-contracts.md 中“superseded 表示修改/删除”的宽泛表述：**裸缺失是 missing；只有可验证的其他 revision 或明确替代凭据才是 superseded。**
显式同版本取消凭据才是 cancelled；找不到旧记录不能推出取消、替换、成功或未发送。
source-contracts.md 的 S2 是修复前证据；S1/S3 仍有效。保留原报告，不覆盖其历史观察。

## 目标写入器的能力边界

现有 `EffectWriter` 是同步 Redis-only API；调用方在线程中调用，并只传冻结数据：

| 任务 | 可接的现有接口 | 必须预先冻结 |
| --- | --- | --- |
| global_history | append_global_record(effect_id, ChatRecord, max_records=...) | 全部记录字段、time、max(1000, 原配置) |
| outbound_dedup | record_outbound(effect_id, OutboundMessageRecord, max_records=..., ttl=...) | message_id、目标、正文、归一化内容/intent、source、created_at、保留参数 |
| news_fingerprints | record_news(effect_id, fingerprints, sent_at=...) | 去重排序后的指纹集合、固定 epoch 对应时间 |
| cost（本三入口不生产） | consume_cost(effect_id, user_id, amount, at=...) | 原计费归属日、用户、金额；不能取重试日 |

历史、出站兼容现有 list key；资讯兼容 news:sent 并取新旧时间最大值；费用在检查两个值和溢出后以一次 MSET 写两个计数器和回执。
永久回执 key 为 `mako:delivery:v1:effect:<64 hex>`，无 TTL；receipt digest 已包含 kind、targets 和实际序列化数据。
现有接口**没有**接收队列 payload_digest，也不校验 action=sent；队列适配层必须补足这些前置条件，不能凭 writer 正常返回证明合法送达。
record_outbound 不替代 dedup.record 的归一化构造；计划构造器需复用 canonical_intent/normalize_outbound_text 并冻结结果，message_id 可直接取稳定 effect_id。
不能每次重试调用旧 dedup.record：它生成新 UUID、当前时间并走非幂等仓库。

已证明的是正常脚本完整执行后的响应丢失、并发相同费用、预检的类型/值错误；Lua 无交错不等于运行时错误回滚。
历史/出站仍为 RPUSH→LTRIM→可选 EXPIRE→SET receipt，多指令而非单命令提交；资讯也为多个 HSET 后写回执。
本轮未确证这些有效输入路径出现局部写错误，不把一般资源故障猜测记成已复现缺陷；也不授予“任意 Redis 错误后均可安全重放”的保证。
接线时至少区分连接/响应未知、已知写前坏数据、不能判定是否局部执行的服务端错误；后一类须 needs_review，不能让统一 EffectUnavailable 驱动无条件自动重试。
这项分类可由 writer 暴露明确错误类型/代码实现，不能依赖日志文本或事后 GET 无回执就推断没有写。
业务 list 的裁剪和 TTL 仍生效；回执存在而历史行已被裁剪属于保留策略，重试不得重新插入。跨任务迟到追加不保证按送达时间裁剪，不能扩展为完整历史归档。

## 最终方案：动作内嵌任务，发送前冻结

新增 `delivery/effects/`，建议 models/plans/store/scripts/worker/__init__ 六文件；目标仍属 persistence，不向 state/ 平铺多个文件。
源目标适配按 followup/reminder 分职责，遵守单文件 <400 行、直属文件不超过 10；本评审不实施文件创建。
保留已有 DeliverySpec.encode/digest/action_id，不把计划塞进 spec 后重算旧身份。

动作新增独立 envelope（以下是待实现契约）：

```text
effects_version=1, plan_json, plan_digest,
confirmation_source=transport|owner, sent_recorded_at_ms,
effects=[{effect_id, kind, codec_version, payload_json, payload_digest,
          state, attempts, lease_token, lease_until_ms, next_attempt_at_ms,
          result_code, time_basis}], effects_state
```

1. effect_id=SHA256(canonical([action_id, 固定语义名, 0]))；不含租约、重试次数、运行时间。payload_digest 单独绑定负载，ID 不随升级重新生成。
2. claim(spec, plan) 同次保存 spec 和 dormant 任务；先校验本 kind 必需任务、数量、字段、大小、源身份、可识别版本。恢复必须使用已存计划。
3. 周期任务用 observed/claim 返回的 frozen.payload 构造计划；禁止使用本次重新抓取的正文/指纹。既有 queued/rejected 缺计划时，只在 begin 前 CAS 安装与原 spec 匹配的计划。
4. begin 除旧 token/期限/源校验外，还检查计划完整；缺计划或不支持版本不允许外发。再次 claim 不重建已冻结 ID/参数。
5. 发送前时间可以是声明式占位符 `first_transport_sent_recorded_at`；不能使用 worker.now。激活时普通 ACK 取首次 Redis TIME，固定 sent_recorded_at_ms/time_basis=transport_recorded，不声称精确外部送达时间。
6. 可接的摘要实现：发送前 Python 固定 plan_json+SHA256；激活脚本填时间后一次 cjson.encode 得到 payload_json，保存 redis.sha1hex(payload_json) 作为明确命名的 payload 摘要版本。重读按保存的原始字符串核对，不用重新排序 JSON 比较。
7. 目标 writer 的 SHA256 receipt digest 与上述队列摘要是两层契约，不比较为同一个值。适配器校验队列摘要后，按 codec_version 确定性构造 writer 参数；禁止默认 UUID/时间/配置补值。未来 codec 改变不能无声改写旧任务。
8. 时间固定为 epoch 毫秒和明确序列化时区；历史/出站适配必须与现有读者的 datetime 比较兼容。不能依赖重启机器本地时区，把同一 payload 映射成不同 target digest。

普通 mark_sent 与人工 reconcile_sent 共用 activate_effects：在内存中验证并构造完整 envelope，成功编码后**最后一次 SET 同时保存 sent 和所有任务状态**。
现有过期 sending→unknown 的保守写可保留；绝不先 SET sent 再填任务，也不在命令返回后 enqueue。
重复 sent/reconcile 返回原计划/时间/操作者/结果；不能清空租约、重置成功任务。人工 cancelled 不激活，晚 ACK 不覆盖 cancelled；人工 sent 后晚 ACK 也不重新计时。
旧 unknown 无计划，人工核对仍可落送达事实，但同次 SET 标 legacy_review/needs_review，不能拼造自动可执行历史任务。

## 三类生产者与时间政策

| 入口 | 必需计划 | ACK 后接线 |
| --- | --- | --- |
| PeriodicDelivery | outbound_dedup + global_history；非空指纹再加 news_fingerprints | 删除旧三类直写；可唤起同一 worker，但不能绕过 claim |
| FollowupDelivery | outbound_dedup + followup_complete | 删除旧 dedup.record/complete(snapshot)；源完成与去重独立推进 |
| ReminderDelivery | reminder_complete | 删除旧 complete(snapshot)；目标需保留旧 action/source/bot/target 校验 |

出站保留参数沿用旧仓库公式并在计划中固定：max_records=max(20, 配置)，ttl=max(86400, max(去重小时, 问候冷却小时)*7200)。历史固定原配置裁剪值。
本三入口没有费用调用；保留 consume_cost 能力，但不制造“消息发送费用”，不顺带接 B1/聊天生成费用。
observe_group_output 保持进程内最佳努力；持久重试不回灌旧群窗口。

普通 ACK：任务使用固定 transport_recorded 时间。人工 sent 无可信实际时间：三个时间相关 kind 均 needs_review/time_unknown；completion 仍 pending。
sent_recorded_at_ms 与 reconciled_at_ms 只是审计时间，不代填业务时间。needs_review 不阻断同动作的 completion。
后续若补实际时间，应是显式、经校验的修订操作；本轮不新增 Owner 参数或放宽时间政策，也不通过晚 ACK 自动改写已冻结人工任务。

**已落地的过渡保护（本轮独立验证）：** 当前 reconcile_sent 在一次最终 SET 中保存 `confirmation_source=owner`、`sent_recorded_at_ms=now`、`delivered_at_ms=null`、`effects_state=needs_review`、`effects_review_reason=actual_delivery_time_unknown`，同时保留核对人/时间/结论。
already_reconciled 及 sent 分支的 already_sent 在 save 前返回；重复核对、冲突核对和晚 ACK 不改首次记录字节。cancelled 后晚 ACK 拒绝，人工结论不可覆盖。
plugins/autonomy/delivery_owner.py:73–74 已在成功已送达反馈明确三种时间补记待核对且不用核对时间替代；实际处理函数经隔离替身反馈探针验证。
当前没有冻结计划，未凭空写 completion 任务是正确的过渡行为；**尚未实现按原版本自动收尾**。未来激活必须细分任务状态，保留 null 实际时间及人工审计信息；不能把整条 needs_review 当作永久停止 completion 的理由。

ACK 已有而 mark_sent 未确认：保持 acknowledged 与 state_confirmed 分离；可有界重试同 token 的 mark_sent/重读，不能再次调用传输或直接写目标。
进程在 ACK 与 sent 持久化之间崩溃，恢复仍是 unknown，需要 Owner 核对；P6 不消除此网络未知窗口。

## 源完成：选用身份接口及永久 effect 回执

收敛选择 source-contracts.md 的第二种方案，不要求恢复旧 snapshot：

```text
complete_effect(effect_id, action_id, source_identity, revision, source_digest)
  -> applied | already_applied | superseded | cancelled
     | missing | inconsistent | wrong_action | conflict | unavailable
```

kind、action_id、user/job/memory 身份、revision、source_digest、bot/target 必须绑定到任务与回执。目标 key 由受信代码按 kind 推导，不能接受持久化任意 Redis 命令。
源 receipt 使用独立命名空间（例如 effect-source:<id>），永久存绑定摘要、结果及必要原始绑定；不得覆盖当前通用 writer 的纯 digest receipt 格式。

原子脚本顺序：

1. 校验参数及 receipt 类型；先查回执。绑定相同则返回保存的结果，成功记录返回 already_applied；绑定不同 conflict。此快路不得依赖当前源/旧 snapshot 仍存在。
2. 无回执时读动作，必须 sent，且冻结 spec 与内嵌 completion 任务绑定一致。保留提醒现有 kind/business/revision/source_digest/bot/target 检查；跟进补同等检查。
3. 原子读取当前正文/revision/意图并分类；同版本正文摘要不符是 inconsistent，不是新版本或已完成。
4. 仅匹配源执行有限变更：跟进标 done、清相应 due member；提醒删匹配正文、保存 complete 调度意图。不改新的 revision，不重建缺源。
5. 预先完成所有类型/JSON/数值验证及编码，源变更、索引后置条件与永久 receipt 在同个 Lua 内完成。完成时间采用首次执行时间并保存在 receipt，不在重试中刷新。
6. 源目标必须有自身错误/局部执行分类，不能仅以“同 Lua”宣称所有错误均回滚。已知后置索引修复可以重做，但不可先凭 receipt 宣告完整再漏清索引。

| 无同 effect 回执时的证据 | 返回/队列行为 |
| --- | --- |
| sent 与原 revision/digest 匹配，成功完成及存回执 | applied，关闭该 effect |
| 可验证当前为其他 revision，或有明确替代版本凭据 | superseded，存永久终结结果；跳过旧源，不称业务已写入 |
| 有明确同 revision 取消意图且身份匹配 | cancelled，保存终结性跳过凭据 |
| 正文和有效替代/取消/完成证据均缺失 | missing→needs_review；不自动删除/新建源或把它改为 success |
| 同 revision 摘要变化、坏元数据、字段间不一致 | inconsistent→needs_review |
| 动作未 sent/身份不匹配/任务不匹配 | wrong_action→needs_review；不执行目标 |
| 同 effect 不同绑定 | conflict→needs_review；保留原回执 |
| 连接/响应未知，且重试满足目标幂等契约 | unavailable→有界退避，重试相同 ID/负载 |

先读永久回执再判断当前源是关键：成功后修改/删除/同 ID 重建，再重放仍应 already_applied；不能被现在的 missing/superseded 掩盖先前成功。
无回执而 done 不能证明本 effect 曾应用。旧跟进同 revision done 的 ZREM 修复是状态后置条件修复；来源摘要已变且缺完成归属证据时默认 needs_review，不能伪造本 action 成功回执。
旧提醒 action_key/revision 完成墓碑可在验证原 sent/source 绑定后转为 legacy_completion_evidence；只终结 completion，不证明任何历史/去重效果。
建议 superseded/cancelled 也留永久分类回执，防止 worker 确认丢失后因下一次源变化得到不同结论。

## 消费者、分页与迁移

`effects.claim(action_id,effect_id)` 在动作 key Lua 中验证 sent、版本、负载摘要、任务状态和到期时间；生成独立 lease_token，Redis TIME 定租约。
`worker.apply(task)` 仅调明确白名单适配器；不持有 bot/dispatch，不走 P5 recover，不检查今天/发送有效期/当前目标配置来取消旧补记。
`finish/defer` 必须 CAS effect_id+payload_digest+lease_token；旧 worker 迟到不得覆盖新认领。成功目标后 finish 丢失，按原 ID 重试命中目标回执。
取消 asyncio.to_thread 的 await 不代表线程停止：不提前释放租约，不声称失败未写，不新建 ID；让租约到期并通过目标回执收敛。
applied/already_applied 为写入成功；superseded/cancelled 为 skipped 并保留原因；其他证据冲突为 needs_review。任务间互不阻断。
聚合状态：全部成功 complete；含跳过但无未决项 complete_with_skips；存在 needs_review 就明确展示它，同时仍消费其他 pending/retry_wait 项。不能仅因 aggregate=needs_review 整条跳过。

扫描使用原动作 key 精确格式过滤，排除 effect/source receipt；单页最多处理 3 个任务并限制读取工作量，游标为 cursor+offset，独立于 P5 发送恢复游标。
SCAN COUNT 非硬上限；重复、空非末页、超量页均须保留续页位置，末尾后开启下一轮。分页不提供并发快照或完成证明。
错误退避有上限，失败保留；未知版本/坏数据隔离。不能将确定性坏目标当无限快速 retry；也不能在固定次数后默认成功或丢弃。

迁移必须按计划/回执证据而非日期分界：

- 新完整任务：不迁移，原 ID/参数续跑。
- 旧 sent 无计划/凭据：CAS 标 legacy_review，保留 sent/spec/token；**历史、费用、去重、指纹不自动重放**。pending 不证明未写，冻结正文也不证明未写。
- 旧源仍匹配原 sent revision/digest：可建立 completion 候选，交新原子源接口验证并记录证据；不基于本地 load 结果直接完成。
- 已有合法 reminder 完成墓碑：只归档同 completion 的证据；后续覆盖过的墓碑不能凭空恢复。
- 缺失/改版/取消按上表分类，不将旧 followup False 或 reminder changed/missing 直接翻译成成功。
- 无计划旧 queued/rejected 在 begin 前受限安装；旧 unknown 不自动送达、补写或恢复传输。
- 迁移和 finish/reconcile 竞争以原记录摘要 CAS 失败后重读，不能覆盖新任务进度。

切换时须停/排空旧直写发送进程，再启用新协议；本文仅写明部署前置条件，不执行停机或部署。
回退应停新 worker/相关发送器并保留全部动作和回执，不能直接回退至忽略任务的旧直写版本。本文自身回退只移除本文。

## 实施阻断与最小验收顺序

| 顺序 | 必须交付 | 针对性验收（当前未实现/未运行） |
| --- | --- | --- |
| 1 | 两种源 complete_effect + 永久绑定回执、错误分类 | 成功后改/删/重建仍 already_applied；无成功证据时 missing/superseded/cancelled 分开；新源不动；错误 action 拒绝 |
| 2 | 计划构造/codec、claim/begin 校验、两条 sent 单 SET 激活 | 坏任务不出现 sent 无任务；普通/人工写后丢响应重试时间与 ID 不变；cancelled/晚 ACK 不覆盖 |
| 3 | 目标错误类型与确定性适配 | 队列摘要不符拒绝；重启/时区/配置变化不改 writer digest；坏数据待核对；未知服务端局部错误不盲重放 |
| 4 | 独立租约 worker + finish/defer CAS | 目标后断连、finish 后断连、取消线程迟到、两消费者竞争；业务效果一次，旧 lease 无权覆盖 |
| 5 | 三类入口一次切换旧直写 + 有界注册扫描 | 实际入口 sent 后立即取消可恢复；unknown 不补记不重发；跨日/bot 离线仍收尾；人工时间待核对不挡源完成 |
| 6 | 有界旧数据分类与人工反馈 | 已直写旧 sent 不重复追加；空非末页/超量/坏记录可续查；迁移重跑幂等且不覆盖新进度 |

以上代码及定向验证完成后才复审 P6 实现闭环；本轮只给可实施契约，不将未来验收表当测试结果。
费用跨入口接入、自动通知、历史补放/删除、生产持久性、Cluster、全项目验收不属于本结论。

## 本轮复现记录与源码快照

解释器：`../.refactor-snapshots/validation-py310/Scripts/python.exe`，`-B` 禁 pycache；pytest 加 `-p no:cacheprovider`。
独立命令：`python -B -m pytest -q -p no:cacheprovider test/delivery/effects/test_effect_targets.py test/delivery/state/test_followups.py::test_complete_repairs_index_after_legacy_done_partial_failure`。
实际结果：**10 passed in 16.39s**（9+1），exit_code=0；未复跑其他现有测试。

随后因用户告知新的人工 sent 补丁，仅追加运行 test_delivery_reconciliation.py 中 unknown_only_idempotent_reconciliation_and_late_ack（False/True 两例）、competing_manual_conclusions_cannot_overwrite_each_other、lost_reconciliation_response_preserves_idempotent_conclusion：**4 passed in 6.67s**。
这些断言覆盖 null 业务时间、owner 来源、needs_review 原因、重复/冲突核对与晚 ACK 字节不变、双人工结论竞争及写后丢响应；未重复前面的 10 项。

新增探针为 stdin 内存脚本，不新增测试文件；复用 `isolated_redis.__wrapped__(Path.cwd())`，finally close。
fixture 启动独立 redis-server、动态回环端口、核验 INFO process_id，禁 RDB/AOF，退出仅终止自己进程。没有连接已有 Redis、没有 FLUSHDB。
四项输出 A 永久回执在合成目标删除后阻止重放、B 换目标冲突、C 资讯坏后项不局部写前项、D 跟进完成后改删仍 False，均断言通过；总墙钟 2.49 秒。
D 是缺口复现成功；C 同时证明错误仍归 unavailable，不能把这四项写成 P6 全通过。
第五个内存探针调用实际 process_delivery_command 的已送达路径，send_to_event 完全 mock；断言反馈包含三种时间补记待核对及不替代时间，动作无伪造 effects，重复人工命令和晚 ACK 后 Redis 字节不变。通过，墙钟 4.71 秒，无真实消息。

| 相对源码路径 | SHA256（本轮读取） |
| --- | --- |
| src/services/persistence/effects/store.py | C5F105B2F491885169CEFCB17A3A175CF36307D55F845F0E4A0B7F5E9F39AD5A |
| src/services/persistence/effects/scripts.py | 25D282DECBAF0CC61473C76033FBAD2B769784AAC4D53A112B999ED0DA0DD5C2 |
| src/services/persistence/followups.py | E1A6E4539A5BF68BC79CFEACDAB1108151B898584C4B96A874C38C874E5E6F63 |
| src/services/delivery/state/scripts.py（人工政策补丁后） | 3EDAF5EC7322B230E1A1F7A84953307412265EB43849B94EB1FD9EAE96478EFA |
| src/plugins/autonomy/delivery_owner.py | CBE3F40C825FBBCA90D3D50FE69B8DB162A8A65C70A95F2FD44A9B8CAB364FE8 |
| test/delivery/state/test_delivery_reconciliation.py | 7D4B07F2F911CB36ED65D05CBF798C002698A39043776580A2793E8857DC914C |

未验证 Redis 重启/磁盘恢复/主从切换、实际网络故障、Python 3.13、本模块生产接线或实群效果。隔离 Redis 无持久化，不能据此声称生产 exactly-once。
此独立综合评审完成；P6 实施与最终验收未完成。未将其他 Agent 的原探针计入本轮测试数。

## 追加复核：目标错误分类补丁（2026-09-26）

本次按用户要求只读复核 EffectNeedsReview 小补丁；重读六文档，16:17:39+08:00 核对工作树，仍无下级 AGENTS.md。唯一写路径为本文，保持原业务及部署边界。
读取时主 Agent 已补 `not isinstance(result, str)` 防护及 `[]` 测试，因此本结论覆盖该补丁，不再把它列为待补。

**本项通过独立复核，关闭前文“目标服务端/坏数据错误均落 unavailable”的分类缺口。** 前文初次评审中的旧错误分类观察保留为历史证据，以本节为当前结论；P6 消费者和源回执等阻断项未因此关闭。

- EffectNeedsReview 直接继承 RuntimeError，与 EffectUnavailable 独立；包入口已显式导出。捕获 EffectUnavailable 不会误捕 NeedsReview。
- EVAL/字节解码范围内，仅 redis.exceptions 和 builtin 的 ConnectionError/TimeoutError 被映射为 EffectUnavailable；其他 Exception 保留 cause 并转 NeedsReview。
- `conflict` 仍为 EffectConflict；成功仅接受 applied/already_applied。None、未知字符串、`[]` 等非字符串返回为 NeedsReview，不因集合 membership 抛裸 TypeError；非法 UTF-8 解码也归 NeedsReview。
- 目标脚本未改：类型/数值预检语义、永久回执和原成功路径保持原实现。坏计数器/错误列表类型现已断言 NeedsReview，不能自动重试。
- 新部分写入测试确实调用隔离 Redis 执行 RPUSH 后 error_reply，确认 all_memory 已有一条合成记录而 receipt 不存在，并断言 NeedsReview 的 cause 为 ResponseError；这是分类边界的有效反例，不是声称生产 APPLY 已发生同样错误。

独立运行（Python 3.10，`-B -m pytest -q -p no:cacheprovider`）：

```text
test/delivery/effects/test_effect_failures.py
test/delivery/effects/test_effect_targets.py::test_bad_second_cost_counter_cannot_increment_first
test/delivery/effects/test_effect_targets.py::test_wrong_list_type_and_invalid_retention_never_write_receipt
```

结果 **11 passed in 5.00s**：四类连接/超时异常、一次真实 Redis 部分写、三类异常返回、两个坏计数器、一个错误类型/非法保留参数用例。仅复跑新增和改动断言，没有重跑目标全套或业务全套，也未将主 Agent 的 16 项结果计入独立结果。
另一个 stdin 内存探针通过：非法 UTF-8 bytes、dict、int→NeedsReview；合法成功 bytes 正常返回；conflict bytes→EffectConflict。没有新增测试文件或调用外部服务。
隔离 Redis 仍使用既有随机回环端口、进程身份核验、禁持久化 fixture；没有生产连接、真实发送或部署。

接线边界仍须保留：worker 将 NeedsReview/Conflict 及发送目标调用前的负载 ValueError 明确映射为 needs_review，不能通过兜底 RuntimeError/Exception 重试它们。本补丁只提供错误类型，尚未落实消费者行为。
redis_client=None 仍显式抛 EffectUnavailable；非法身份/参数和 JSON 序列化校验在 EVAL 前，继续保留 ValueError/TypeError 等写前拒绝，并非“所有 Python 异常统一 NeedsReview”。
本测试证明收到服务端错误时不盲重放；没有验证“服务端局部错误同时丢失错误响应”、Redis 持久性或进程重启。因此仅连接异常分类也不能提升为任意复合故障下 exactly-once 保证。

| 补丁后文件 | SHA256 |
| --- | --- |
| src/services/persistence/effects/store.py | 7D2DC27F6904FEF3CF8DB4DCF0F4FD4B1C84D7A7A3599FAF30C3A29C83649E68 |
| src/services/persistence/effects/__init__.py | 46E8BAB2C740F6E7CA91CB4D47DECA932120DAB595126D2283E4DDA10D6C6F56 |
| test/delivery/effects/test_effect_failures.py | 630E035C4B7BFAF5121D5686A30FF06704EBC465DB28F3A44F0B3B0F745B57F0 |
| test/delivery/effects/test_effect_targets.py | 76322BF38C797230B871D1F79B8628343DB56019DED2A930A5FC84B43AD15AE9 |

scripts.py SHA256 仍为前表 25D282DE…0DD5C2。未改业务、测试或其他文档；回退本次评审仅撤销本追加节，不回退主 Agent 补丁。
