# P6 源完成幂等契约：只读核对

## 开工与边界

- 日期：2026-09-26，Asia/Shanghai；六文档重读及源码核对于 11:16 前开始，探针随后执行。
- 模块：已批准 P1–P6 中的 P6「源完成」旁路评审。批准依据为本次用户指令及 status.md 的 2026-09-24 记录。
- 工作区：`D:/vscode workplace/fun/bot/mako-bot-refactor`；HEAD 为 `8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9`。评审对象为未提交工作树，不能用 HEAD 代替本次文件指纹。
- 已重读：根 AGENTS.md、docs/agent/project.md、development.md、docs/refactor/plan.md、modules.md、status.md；搜索未发现下级 AGENTS.md。
- 唯一落盘路径为本文件。未修改业务代码、测试文件、其他文档；不涉及主 Agent 的历史/费用/去重目标写入。
- 保留契约：只对原版本完成；晚到确认不能清理新版本；未知发送不能重发；Redis 不可用不转内存成功；不触碰原 mako-bot、真实数据或部署。
- 验证范围：followups.py、reminder_state/*；只读关联关系仓库、发送调用方及隔离 fixture；8 个源完成探针，不跑全套。
- 当前会话未暴露 spawn/delegate 等子 Agent 工具，不能在本会话执行“2–3 子 Agent + 另一个综合评审”。本文件仅是一个范围内评审输入，交主 Agent 组织综合评审。
- 本轮没有发生额度失败；工具不可用不能冒充额度失败，既往额度错误也不能当成本轮评审结果。

## 结论

现有接口具备**同版本、完成证据仍保留条件下的状态幂等性**，不能直接等同于 P6 所需的、跨后续修改仍可确认结果的 effect 级幂等目标。

`FollowupSource.complete(snapshot)` 同版本重复返回 True，第一次完成后的时间戳不会被重复改写；旧版本返回 False，不覆盖新版本。它不验证发送 action/sent，调用方必须先验证相应发送证据。

`ReminderStateStore.complete(snapshot, action_key=...)` 首次要求绑定该源的 sent action；删除正文后保留完成意图，重复返回 `ok=True, code=already_completed`。旧版本拒绝，不删除替换记录。完成意图仍在时，返回已经完成不依赖再次读取 action，这里是使用保存的完成凭据，不是再次授权发送。

两者在原快照仍可取得、完成凭据未被覆盖时，都通过了“Redis 已执行 EVAL，客户端随后抛连接异常，再以新仓库实例重试”的探针。**上述通过不覆盖完成后的业务修改、删除或同 ID 重建。**

## 确证问题与影响

### S1：后续合法操作覆盖完成凭据，旧补记无法确认先前成功

证据：followups.py:49–54、62–69；relationships.py:91–124；reminder_state/scripts.py:28–41、69–83、89–97。

- 跟进完成后，业务正文仍在；随后 `update_relationship_memory` 会生成新 revision。原快照重试得到 False；删除后同样 False。
- 提醒完成后 `operation=cancel, reason=complete` 意图允许显式同 ID 重建；create 覆盖 revision/intent。旧 complete 返回 `changed`；若再取消新记录，旧 complete 返回 `missing`。
- F2、R2 实际复现了以上返回值，并验证新状态未被旧完成修改。
- 因而“目标完成成功 → 响应丢失/worker 未记成功 → 业务修改/重建 → 重试”无法仅靠当前返回值辨别“曾完成”与“从未完成”。旧快照不破坏新版本是正确行为，但无限重试 False/changed/missing 会留下不能收敛的 pending。
- 没有确证重复发送或新版本被旧 complete 删除；这里缺失的是补记结果的持久可判定性。

建议：完成回执按稳定 effect_id/源身份/revision（并绑定 action_id）保留，不能随着当前业务记录复用而覆盖。首次源变更和回执写入必须在同一原子操作里完成；先查相同 effect 的回执，再处理当前版本。回执保留期必须覆盖补记重试期，清理策略另行明确。

### S2：跟进的 already-done 快路返回成功，但可能未清理到期索引

证据：followups.py:50–54 在 raw 不同但 revision 相同、status=done 时直接返回 1，未执行 64–65 的 ZREM。关联旧入口 relationships.py:130–145 分两条 Redis 命令写 done 与删除到期索引，不更新 revision。

F4 故障注入使用真实 `mark_relationship_done`：HSET 成功，代理在 ZREM 前抛 ConnectionError；随后拿之前的 active 快照调用 `FollowupSource.complete`。实际返回 True，而 `relationship:followups` 中该 member 仍存在。

影响：如果 P6 将 True 解释为“状态与索引完整完成”，会提前关闭该 effect，漏掉残余索引修复。load 的 active 状态检查仍拒绝已 done 的源，故本探针不证明会重复发送；残余索引会继续被扫描。

建议：同 revision、已 done 分支仍在 Lua 内幂等 ZREM 对应 member，再返回 already_applied；不得对不同 revision 进行索引清理。旧入口是否改成原子完成留给主 Agent 决策，本次未修改它。

### S3：恢复入口不能只持有 ID 再 load，且 bool 不足以表达补记结局

证据：followups.py:102–119、reminder_state/store.py:29–43、99–100；现有两个 complete 都要求原 snapshot。完成后两个 load 均返回 None（F1、R1 实测）。

- 跟进 load 需要到期索引、revision 和 active 状态，成功完成后无法重新拿到旧快照；提醒正文成功后已删除。
- 现有 DeliverySpec 保存 source_digest 等绑定信息，没有保存完整原 raw。不能从 digest 还原原快照，也不能使用更新后的正文冒充旧快照。
- followup 的 False 合并缺失、版本变化、正文冲突；True 也没有 action/effect 级归属信息。reminder 的 `missing/changed` 能表达当前拒绝原因，但不足以解决 S1 的历史成功判定。
- ReminderMutation 是数据类：必须检查 `.ok`，不能用 `if result` 判成功；拒绝结果也是非空对象。现有 ReminderDelivery 已正确检查 `.ok`。

建议二选一：P6 原子入队时持久保存所需旧快照；或增加面向效果的源仓库接口，用源 ID、revision、digest 与 action/effect 身份执行原子校验和完成。优先后者，减少为了完成删除而长期复制业务正文；仍需 S1 的完成回执。

## 接口建议（仅建议，未实施）

建议显式接口形状：`complete_effect(effect_id, action_id, source_identity, revision, source_digest)`，以不可变绑定为依据，不在重试时选择“最新源”。

| 返回 | 队列可采取的动作 |
| --- | --- |
| applied / already_applied | 同一 effect 的成功回执已确认，允许关闭源完成 effect |
| superseded | 当前源为另一版本；保持新源不动，按约定记录终结性跳过，不能谎报原版本已完成 |
| cancelled | 有同版本明确取消凭据；按约定记录终结性跳过 |
| missing / inconsistent / wrong_action | 证据不足或冲突，保留待核对；不能把任意 missing 当成功 |
| unavailable | 结果未知；保留任务，在支持回执幂等的接口上重试，不重发消息 |

superseded/cancelled 是否可终结必须由 P6 编排明确；不能简单把现有 False 映射成 superseded，因为它包含多种原因。

原子边界需要覆盖：校验 effect 身份与已确认 action、查旧 effect 回执、校验源版本/摘要、源完成及对应索引清理、写 effect 回执。相同 effect_id 携带不同绑定参数应报冲突，不返回已完成。

跟进目前没有 action 校验：若仍保留 complete(snapshot)，必须由补记调用方保证该 action 已持久 sent 且来源绑定一致；仅有业务 status=done 不足以证明这个 action 已送达。提醒目前首次完成已经校验 kind/business_id/revision/bot/source 摘要/target 及 sent；建议保留这些检查。

旧未版本化跟进由 load 隔离而非自动完成；旧提醒仅未来项迁移。这些旧数据不能因补记器发现业务 ID 而自动补 revision、完成或重发。

## 本轮测试证据

运行环境：Python 3.10.20，`../.refactor-snapshots/validation-py310/Scripts/python.exe -B -`，在仓库根通过 PowerShell here-string 输入内存脚本。没有落盘探针脚本或生成 pycache/pytest cache。

复用 `test/autonomy/test_pending_atomic.py::isolated_redis.__wrapped__(Path.cwd())` 生成器并在 finally 中 close。fixture 启动 `D:/redis/redis-server.exe`，动态回环端口、禁用 RDB/AOF、核对 INFO process_id 后才写合成数据，最后终止它启动的进程；没有连接已有 Redis 或执行 FLUSHDB。

探针用真实仓库与 Lua；响应丢失代理先执行 `client.eval(...)` 再抛 ConnectionError。新建仓库对象重试，不模拟 Redis 重启。业务关系创建使用合成 content 和自动 memory_id，提醒使用独立 fixture ID；发送状态直接由 DeliveryStore claim/begin_send/mark_sent 准备，不调用 QQ/HTTP/付费模型。

| 编号 | 关键场景和实际断言 |
| --- | --- |
| F1 | 完成写后丢响应；新 Source 重试 True；done 正文字节不变，load None |
| F2 | 完成后更新内容；原快照 False 且不覆盖新正文；删除后仍 False |
| F3 | active 源更新产生新版本；旧 complete False，新正文不变 |
| F4 | 旧 done 入口 HSET 成功、ZREM 抛错；complete True，但 due member 仍在，确证 S2 |
| R1 | sent 源完成写后丢响应；新 Store 重试 already_completed，意图不变、load None；另一 action key 被拒绝 |
| R2 | 完成后同 ID 重建；旧 complete changed 且新源不变；新源取消后旧 complete missing |
| R3 | sent 旧源被 replace；旧 complete changed，不清理新源 |
| R4 | queued 和 sending 两阶段 complete 均 not_confirmed，源不变 |

实际输出：`RESULT: 8 targeted probes passed; no transport called`，进程 exit_code=0，工具记录墙钟 3.22 秒。这里 passed 表示断言观察成立，F4 是缺陷复现成功，不表示契约已修复。

已阅读现有 test_reminder_source.py 的同版本重复、旧 ACK/新版本、错误 action 绑定用例，以及 test_followups.py 的发送/旧版本隔离用例；本轮没有再运行这些完整测试文件，不能把历史结果计入这 8 项。

### S2 最小复现核心（需上述隔离 client `c`）

```python
repo = RelationshipsRepository(SimpleNamespace(redis=c))
source = FollowupSource(c)
m = repo.add_relationship_memory(
    7, "promise", "synthetic",
    due_at=datetime.now() - timedelta(seconds=2))
s = source.load(7, m.memory_id)
proxy = Mock(wraps=c)
proxy.zrem.side_effect = ConnectionError("after HSET")
try:
    RelationshipsRepository(SimpleNamespace(redis=proxy)).mark_relationship_done(
        7, m.memory_id)
except ConnectionError:
    pass
assert source.complete(s) is True
assert c.zscore("relationship:followups", f"7:{m.memory_id}") is not None
```

### 响应丢失注入核心

```python
def lose(script, *args):
    c.eval(script, *args)
    raise ConnectionError("response lost after EVAL")

# followup: FollowupSource(Mock(eval=lose)).complete(snapshot)
# 抛 ConnectionError 后，用 FollowupSource(c).complete(snapshot) 重试。
# reminder: ReminderStateStore(Mock(eval=lose)).complete(snapshot, action_key=key)
# 抛 ReminderPersistenceUnavailable 后，用正常 Store 重试相同 snapshot/key。
```

### 源码快照 SHA256

| 文件（相对 src/services/persistence/） | SHA256 |
| --- | --- |
| followups.py | 485398b1474261610c898b4ba4c07fecc2d77cb2a615e5000842e5dcbb458cd3 |
| reminder_state/scripts.py | edc14cf41d009637777e917d4d170ee3fe29fdc2cf31fe63133d46ed8e0bc3fc |
| reminder_state/store.py | 11ea7edff5e75863094c8060146004d5963e1f57b59ca6c9db28f41f70cdfda1 |
| reminder_state/models.py | 13ac61ec04a4adde6ef331b6245ec1972e4f8ccb7e41060cbea0f1d49ca9efae |
| reminder_state/__init__.py | 57288be8ae31b206b42dcee0c504511e25e906d173dafa6a5585fb858c5d1b0f |

## 限制与交接

- 未测 Redis 崩溃、磁盘持久化、主从切换、Redis Cluster、真实网络丢包；fixture 禁止持久化，不能证明生产故障后的数据保存。
- 未做 Python 3.13 或全套测试；没有并行线程竞争探针，本轮用确定性顺序和故障注入覆盖指定交错。
- 此次只验证 completion 目标；未验证 P6 任务入队、effect 领取、主 Agent 的历史/费用/去重实现或最终队列收敛。
- 默认 python 缺 redis，py launcher 未发现注册 Python；随后使用已有隔离验证环境成功，未安装依赖或借用原 mako-bot 环境。
- 当前源 complete 的旧版本保护有确证；将其直接登记为“可无条件自动重试并得到可终结结果”不通过本范围评审。S1/S3 需补明确结果/持久凭据契约，S2 需修正成功分支的索引后置条件。
- 本次未修复问题，未提交/部署。独立综合评审尚未由本会话完成。回退只需移除本文件，不修改业务状态或其他 Agent 产物。
