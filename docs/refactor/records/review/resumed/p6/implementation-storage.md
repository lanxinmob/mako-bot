# P6 实现独立复审：持久化目标与消费协议

## 审查记录

- 日期：2026-09-27（Asia/Shanghai）；开工先重读六文档，过程时钟核对为 17:23:13，补充验证后为 17:25:59。
- 模块与授权：本次用户明确要求串行独立复审 P6；仅本评审者执行，没有派发其他 Agent。主 Agent 的上线/回退边界不属于本文审查。
- 已读：根 AGENTS.md、docs/agent/project.md、docs/agent/development.md、docs/refactor/plan.md、docs/refactor/modules.md、docs/refactor/status.md。仓内 rg --files -g AGENTS.md 仅返回根文件。
- 代码范围：src/services/persistence/effects/ 全部 7 个 Python 文件；src/services/delivery/effects/{plans,activation,models,scripts,store,targets,worker}.py。为核对调用契约，只读了 state、模型、既有目标仓库与相关测试辅助代码。
- 唯一允许及实际持久写路径：本文 docs/refactor/records/review/resumed/p6/implementation-storage.md。未修改业务代码、测试文件或其他文档。
- 保留契约：unknown 不消费、不发送；sent 与任务同次激活；冻结身份/负载/时间/参数；永久回执；源版本绑定；过期租约接手不能覆盖新持有者；人工时间未知不补造历史时间。
- HEAD 为 8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9，但大量实现尚未提交，不能用 HEAD 代表本次实现；文末记录审查文件 SHA256。
- 历史 queue-contracts.md / synthesis.md 仅用于对照目标契约与已接受限制，未作为实现通过证据。

## 结论

**发现 1 项 P1：部分 Lua 写入的待核对结论没有可靠跨越取消、结算失败或错误响应丢失；租约接手会重复追加，并把任务最终标为 complete。本范围暂不通过实现验收。**

这不是声称正常有效输入必然触发 Redis 内部错误。本轮通过显式服务端故障注入，证明实现不能保持其“部分执行错误不得自动重试”的协议；没有复现真实资源耗尽、服务器崩溃或生产故障。

## S1 · P1：部分执行没有持久屏障，恢复会把未知部分写入再次执行

### 路径与根因

- src/services/persistence/effects/scripts.py:13–17、52：history/outbound 先 RPUSH，后裁剪/过期，最后 SET receipt。Lua 不交错，但运行时失败不会回滚已完成命令；因此存在“已有业务行、没有 receipt”的可区分中间结果。
- src/services/persistence/effects/store.py:43–50：服务端错误转 EffectNeedsReview；连接/超时转 EffectUnavailable。错误类型只存在于返回调用栈，目标存储没有永久失败/执行中凭据。
- src/services/delivery/effects/worker.py:25–44：收到 EffectNeedsReview 后另一次 finish 才写 needs_review；finish 未提交就返回 settlement_unconfirmed。取消 to_thread 等待则根本不会结算后台线程后来的错误。
- src/services/delivery/effects/scripts.py:29–39：到期 leased 与到期 retry_wait 可以再次认领，没有检查“上一轮目标可能部分执行”的持久证据。
- src/services/delivery/effects/scripts.py:49–55：旧租约无法结算是正确 fencing，但不能恢复丢失的目标错误结论；后续完整执行 applied 又会写 complete。

### 可复现交错及实测结果

所有情形使用真实 DeliveryStore claim/begin/sent 激活周期计划，认领真实 global_history 任务；只在 Redis 执行的 APPLY 字符串内将 LTRIM 替换为 error，使生产 RPUSH 已执行、receipt 尚未写入。业务文件未改。每个情形单独启动并关闭既有 isolated_redis fixture。

| 情形 | 首轮返回 | 首轮持久任务状态 | 同 ID/同载荷接手结果 | 历史行数 |
| --- | --- | --- | --- | --- |
| 对照：错误结论成功结算 | invalid_payload | needs_review | not_claimed | 1 |
| finish 提交前连接失败 | settlement_unconfirmed | leased | applied → complete | 2 |
| 取消等待，后台线程随后抛出服务端错误 | cancelled | leased | applied → complete | 2 |
| 服务端已部分执行，但错误响应在连接层丢失 | unavailable | retry_wait | applied → complete | 2 |

三个缺陷情形均断言：首轮 receipt 不存在；接手后两条记录逐字节相同；任务最终 complete。使用既有 rewrite_task 将 lease_until_ms / next_attempt_at_ms 置 0，仅加速到期，不修改载荷、回执或任务状态。不是重复消息传输的复现；受影响的是历史/出站列表补记的幂等性与任务结论。

S1 不因“捕获更多异常”“取消时不释放租约”“延长租约”而消失：部分执行发生在服务端，而错误可能从未到达消费者。已有测试覆盖完整目标提交后的丢响应、正常结束线程的取消、成功 finish 的丢响应；没有覆盖本次部分写入与上述故障的组合。

### 建议修复

将“可能已执行”与成功回执区分，并使该证据在第一条不可重放目标变更之前持久可见；重试遇到未完成凭据必须返回待核对或走能证明安全的修复流程，不能等同于未执行。可采用永久 started/committed 目标协议，明确处理迟到线程与旧租约；started 不能提前冒充 applied，也不能只靠内存异常结果落状态。

更强的方向是把业务值与成功凭据纳入单命令提交，或将目标结构改为按 effect_id 真正可幂等更新。现有费用 MSET 是单命令提交总额和回执，不能直接据此推断 RPUSH 列表具有相同保证。仅捕获 Lua 错误后再写失败标志，也需要覆盖该标志写入失败的窗口。

修复验收至少保留本次四情形，并增加旧线程跨租约到期后才结束、源完成部分更新后缺回执的交错。不要通过自动重发消息、重建 effect_id 或清除旧证据解决。

## 其他审查证据与边界

- **原子激活**：activation.py:87–120 在内存中实例化任务；调用方 state/scripts.py 的 save 最终单 SET 写 sent 与完整 effects。重复 sent/reconcile 提前返回，不重置任务。此为静态核对；本轮未重跑整个状态套件。
- **冻结负载**：plans.py:38–65 重建并严格比对模板，models.py:48–99 校验动作/spec/计划、实例化负载与摘要；store.py:43–53 以验证过的原始快照 CAS 防止验证后被替换。targets.py:18–56 从冻结毫秒与时区偏移构造记录，未使用当前时间补历史。定向恢复参数变化、篡改载荷、周期三类目标与重复消费检查通过。
- **源回执**：source_scripts.py:15–25 先检查永久回执及完整 binding，然后才检查当前 action/source；followup_source.py 与 reminder_source.py 对源版本、正文摘要和显式取消分别处理。两类“完整写入丢响应→源改版/重建→源删除→旧 effect 重试”断言通过；同 ID 改载荷拒绝，receipt TTL=-1。这两项复用的 install_task 是合成 envelope，只证明目标接口，不冒充生产接线验证。
- **源部分写入限制**：followup_source.py:25–27 和 reminder_source.py:39–41 仍分步修改业务状态、索引/意图及最终 receipt；本轮没有对两类源逐命令注入故障，不能称其具备任意 Lua 失败后的原子回滚/可恢复保证。
- **租约**：scripts.py:5–15 的原始快照 CAS 与 :41–49 的 token/到期 fencing，定向确认旧 lease 不能 finish/defer 新 lease。本次取消探针真实使用 threading.Event 控制后台线程并传播 CancelledError；没有声称取消 await 能停止线程。
- **人工未知时间**：activation.py:105–119 将时间任务设 needs_review、unknown，并保留 sent_at_ms=null / delivered_at_ms=null；源任务仍 pending。models.py:86–89 拒绝把该时间任务变为可执行状态。真实计划激活与 worker 检查确认 followup 源可完成而出站无写入，聚合仍 needs_review。
- **目标预检**：通用脚本先校验 Redis 类型；费用先校验两个数值/溢出，再 MSET 两总额及回执；资讯写入取新旧时间最大值。以上静态核对，未把既有测试成绩重新计入本轮。
- 已接受的按追加顺序裁剪列表、不保证迟到补记按送达时间保留最新条目，仅记录为契约限制，未另列为新发现。
- 未复审 producer/discovery、三个发送入口、Owner 路由、上线/回退操作；未跑全套、Python 3.13、生产 Redis、持久化重启/主从切换、Redis Cluster、QQ 或模型服务。没有给 P6 全链路通过结论。

## 本轮执行方式与复现

解释器均为仓库根相对路径 ..\.refactor-snapshots\validation-py310\Scripts\python.exe，实际 Python 3.10.20；使用 -B 禁止写 pyc。以下 Python 块通过 PowerShell here-string 管道输入该解释器的标准输入执行；没有落盘探针文件。Settings.model_config["env_file"]=None 在辅助模块导入前禁用 dotenv。

既有 test/autonomy/test_pending_atomic.py::isolated_redis 启动 D:\redis\redis-server.exe，随机 127.0.0.1 端口、禁用 RDB/AOF，INFO process_id 匹配新进程后才写入；finally 关闭客户端并终止自身进程。不连接现存服务、不 FLUSHDB。每次运行使用新的 fixture，不复用合成业务键到下一情形。

运行形式：

~~~powershell
@'
# 将下面任一完整 Python 块放在这里
'@ | & '..\.refactor-snapshots\validation-py310\Scripts\python.exe' -B -
~~~

### 新增故障探针（4 情形，约 9.03 秒，退出码 0）

退出码 0 表示断言确认了上表行为，包含三条缺陷复现；不能写成“四项功能通过”。

~~~python
import asyncio, json, sys, threading
from pathlib import Path
from types import SimpleNamespace
from src.core.config import Settings
Settings.model_config["env_file"] = None
from redis.exceptions import ResponseError
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.effects.test_effect_leases import activate, rewrite_task
from src.services.delivery.effects.store import EffectStore
from src.services.delivery.effects.targets import EffectTargets
from src.services.delivery.effects.worker import EffectWorker
from src.services.persistence.effects import EffectWriter
from src.services.persistence.effects.scripts import APPLY

async def probe(client, mode):
    spec, store = activate(client)
    task = store.inspect(spec.action_id).tasks[1]
    receipt = "mako:delivery:v1:effect:" + task.effect_id
    started, release, ended = threading.Event(), threading.Event(), threading.Event()
    def partial(*args):
        script = args[0].replace(
            "redis.call('LTRIM', KEYS[2], -p.max_records, -1)",
            "error('injected post-RPUSH failure')")
        assert script != args[0] and args[0] == APPLY
        try:
            return client.eval(script, *args[1:])
        except ResponseError:
            if mode == "lost_error":
                raise ConnectionError("injected lost server error response")
            if mode == "cancel":
                started.set()
                assert release.wait(5)
            raise
        finally:
            ended.set()
    targets = EffectTargets(client)
    targets.writer = EffectWriter(SimpleNamespace(eval=partial))
    def fail_settle(*args):
        if args[6] == "finish":
            raise ConnectionError("injected failure before finish commit")
        return client.eval(*args)
    worker_store = (EffectStore(SimpleNamespace(get=client.get, eval=fail_settle))
                    if mode == "settle_failure" else store)
    worker = EffectWorker(client, store=worker_store, targets=targets)
    if mode == "cancel":
        running = asyncio.create_task(worker.run_task(spec.action_id, task.effect_id))
        try:
            assert await asyncio.to_thread(started.wait, 3)
            running.cancel()
            try:
                await running
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("cancellation swallowed")
        finally:
            release.set()
            assert await asyncio.to_thread(ended.wait, 3)
        first = "cancelled"
    else:
        first = await worker.run_task(spec.action_id, task.effect_id)
    state = store.inspect(spec.action_id).tasks[1].state
    assert client.llen("all_memory") == 1 and not client.exists(receipt)
    if mode == "control":
        assert state == "needs_review"
        second = await EffectWorker(client).run_task(spec.action_id, task.effect_id)
        assert second == "not_claimed" and client.llen("all_memory") == 1
    else:
        rewrite_task(client, spec, task.effect_id, lease_until_ms=0, next_attempt_at_ms=0)
        second = await EffectWorker(client).run_task(spec.action_id, task.effect_id)
        rows = client.lrange("all_memory", 0, -1)
        assert second == "applied" and len(rows) == 2 and rows[0] == rows[1]
        assert store.inspect(spec.action_id).tasks[1].state == "complete"
    print(mode, first, state, second, "rows=" + str(client.llen("all_memory")))

print("python", sys.version.split()[0])
for mode in ("control", "settle_failure", "cancel", "lost_error"):
    fixture = isolated_redis.__wrapped__(Path.cwd())
    client = next(fixture)
    try:
        asyncio.run(probe(client, mode))
    finally:
        fixture.close()
~~~

实测 stdout：

~~~text
python 3.10.20
control invalid_payload needs_review not_claimed rows=1
settle_failure settlement_unconfirmed leased applied rows=2
cancel cancelled leased applied rows=2
lost_error unavailable retry_wait applied rows=2
~~~

另有一行预期告警：Effect task settlement unconfirmed; retained for reconciliation。

### 针对其他审查疑点的既有断言复核（7 情形，全部 PASS）

直接调用选定测试函数，每项使用独立 fixture；没有启动 pytest 全量收集。这是七项定向检查，不能与历史测试数相加宣称全套通过。

~~~python
import asyncio
from pathlib import Path
from src.core.config import Settings
Settings.model_config["env_file"] = None
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.effects.source_fixtures import make_source, install_task
from test.delivery.effects.test_source_completion import test_source_write_response_lost_then_source_recreated_retains_receipt
from test.delivery.effects.test_plan_activation import test_recovery_preserves_original_retention_despite_configuration_change
from test.delivery.effects.test_effect_leases import test_expired_worker_cannot_finish_or_defer_new_lease, test_invalid_payload_does_not_receive_a_lease
from test.delivery.effects.test_effect_worker import test_owner_unknown_time_only_completes_original_source, test_periodic_tasks_write_frozen_records_and_complete_once
checks = [
    ("source_receipt_followup", "followup"),
    ("source_receipt_reminder", "reminder"),
    ("frozen_recovery", test_recovery_preserves_original_retention_despite_configuration_change),
    ("old_lease_fenced", test_expired_worker_cannot_finish_or_defer_new_lease),
    ("payload_tamper_rejected", test_invalid_payload_does_not_receive_a_lease),
    ("owner_unknown_time", test_owner_unknown_time_only_completes_original_source),
    ("frozen_codec_repeat", test_periodic_tasks_write_frozen_records_and_complete_once),
]
for name, check in checks:
    fixture = isolated_redis.__wrapped__(Path.cwd())
    client = next(fixture)
    try:
        if isinstance(check, str):
            repo, snapshot, spec = make_source(client, check)
            install_task(client, spec)
            result = test_source_write_response_lost_then_source_recreated_retains_receipt((client, repo, snapshot, spec))
        else:
            result = check(client)
        if asyncio.iscoroutine(result):
            asyncio.run(result)
        print(name, "PASS")
    finally:
        fixture.close()
~~~

实测逐项输出 source_receipt_followup、source_receipt_reminder、frozen_recovery、old_lease_fenced、payload_tamper_rejected、owner_unknown_time、frozen_codec_repeat 均为 PASS；进程退出码 0。

## 实现快照 SHA256

以下为本轮读取、探针后核对的文件内容；用于识别后来补丁，不代表已提交版本。

| 路径 | SHA256 |
| --- | --- |
| src/services/persistence/effects/__init__.py | 46e8bab2c740f6e7ca91cb4d47deca932120dab595126d2283e4dda10d6c6f56 |
| src/services/persistence/effects/followup_source.py | 43d416b8c2bc87ba611a34190b00813f2eee3c411729cf32d0bebe9338acabdb |
| src/services/persistence/effects/reminder_source.py | 780a848bb6d82e7138fb6a12cc40fd09873f5e7a2fd6259288681175e6c94451 |
| src/services/persistence/effects/scripts.py | 25d282decbaf0cc61473c76033fbad2b769784aac4d53a112b999ed0da0dd5c2 |
| src/services/persistence/effects/source.py | a7699d5ae3ad4b9accdbfd387fd41832bcaa033ea0ca81a4cfd415fcd546cc52 |
| src/services/persistence/effects/source_scripts.py | bda54421a7a2a598844e8f5e58491f74d4c5e5c92d129237438c4b154f89ceb6 |
| src/services/persistence/effects/store.py | 7d2dc27f6904fef3cf8db4dcf0f4fd4b1c84d7a7a3599faf30c3a29c83649e68 |
| src/services/delivery/effects/plans.py | 37924cf4935b7e44a975b94745e1cb04af662365e48cbf157a7a219766a3893a |
| src/services/delivery/effects/activation.py | e7a96a20464d76416309e0b3b4d083f515a9d0ae8adddde9e43085af7d88c742 |
| src/services/delivery/effects/models.py | 271097d5970096e9a9a5a991367807b7a558f42a24d9ae84124c2e2268822fd4 |
| src/services/delivery/effects/scripts.py | 260f1035fd97b9272eb24c856b7013ca7d416f43ad5319a9709950eb0d9171f8 |
| src/services/delivery/effects/store.py | 30de8d13643a34e77312d96e82df177cd9d4023235cc627a5d65f86569e5ef13 |
| src/services/delivery/effects/targets.py | 3c8846a9cfafe01276704b43a49bcf426210689efa785b658a3462cb20bc807d |
| src/services/delivery/effects/worker.py | 0eda2122101a5b0fb5682c58e08b7f43885ddec715f9336c2b9b5e1892ede7e8 |
