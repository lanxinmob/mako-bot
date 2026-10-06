# G1 普通聊天计费：独立实现评审

## 开工与范围

- 评审日期：2026-09-30；规范重读与代码检查于本次会话完成，记录时间 11:22 +08:00。
- 已读根 AGENTS.md、docs/agent/project.md、development.md、docs/refactor/plan.md、modules.md、status.md；额外核对 audit.md 及 records/chat/B3.md 的 G1 批准与契约。相关 src/docs 路径未发现下级 AGENTS.md。
- 授权：本次用户指定的独立只读分项评审。唯一交付写入为本文；不修改业务代码、测试、状态文档或发送回执集成。
- 检查对象：persistence/generation 全包、chat/generation 全包；ChatEngine、facts、pipeline/execution 的调用/计费接线，LLM 工厂与 chat/recovery 注册。费用目标仅追踪 G1 实际依赖的 EffectWriter.consume_cost/Lua，不重新评审整个 P6。
- 保留契约：持久准入未确认不得调用主模型/事实检查模型；取消、超时、响应丢失不得自动重调；费用与发送独立，使用冻结日期、金额和稳定 effect_id；未知结果不猜测金额。
- 工作区原有大量未提交内容保留。结论针对本次读取的工作区实现，不代表已提交或部署版本。

## 结论

本次限定范围未确认需要阻断该实现的新增 P1/P2 缺陷。持久准入、单次 provider 调用、费用幂等与跨日归属的核心安全契约具有代码及定点验证依据。

可作为 G1 本分项的附限制评审意见交后续综合；不能据此宣布 G1 全闭环、F1 总体验收或生产可靠计费完成。以下证据缺口和恢复时延风险必须随结论保留，不将待决策事项包装成已经修复，也不将风险推测列作确定缺陷。

## 核查结果

| 核查项 | 实际依据与结论 |
| --- | --- |
| 持久准入失败 | invocation.py:62–67 等待 start 确认后才调用 provider；store.py:46–50 仅首次 started 返回 token，scripts.py:6–13 已有键不重新授权。断连、写后丢响应、已有记录均拒绝调用。取消等待 start 后，即使线程晚写入，也不会调用模型。 |
| 实际模型入口 | engine.py:76–77 主回复及 :156–159 事实校验分别经过 _call_llm/call_recorded；provider.py:37–44 在准入后的回调内构造 SDK 请求。facts.py 的异常 fallback 不重新调用失败模型。 |
| 取消及模型响应丢失 | invocation.py:68–79 将 provider 异常/取消保留为 unknown；标未知失败则保留 calling，无重新授权路径。恢复扫描只调用费用 worker，不持有模型回调。 |
| SDK 重试 | provider.py:39 使用 with_options(max_retries=0)。不仅检查 Mock 的调用参数，另以实际安装的 AsyncOpenAI 和 httpx.MockTransport 注入 HTTP 500，确认仅一次 HTTP 请求，记录 unknown。未访问外部地址。 |
| 估算时点 | invocation.py:47–60 复制输入并冻结日期/费率；:79–87 按未 strip、截断、补引用前的原始输出计费。事实校验独立一条记录。provider.py 返回后的展示变化不修改已冻结金额。 |
| 幂等及跨日 | GenerationSpec.cost_effect_id 由 attempt_id 稳定派生；cost_worker.py:19–21 使用 spec.cost_day。目标 effects/scripts.py 的 cost 分支以单次 MSET 写两个计数器及永久回执，丢响应后同 ID 重试命中回执。不是按重试当天补账。 |
| 费用租约 | costs.py:81–93、cost_scripts.py 将费用租约 token 与模型 token 分开；旧 token 不可收尾新租约。worker 取消不释放仍可能执行的写线程；后续仍依稳定目标回执去重。此项本轮主要为静态核查，没有重跑全部交错测试。 |
| 发送独立性 | pipeline/execution.py:139 只报告费用状态，不再次 consume_cost；生成后的候选失效/发送失败不撤销已写金额。发送回执本身由主 Agent 评审，本项不出具其结论。 |
| 恢复接线 | chat/__init__.py:9 导入 recovery；recovery.py:70 注册 30 秒任务，:94–99 独立调用 GenerationCostScanner 并保存独立游标。前面发送恢复异常不会直接跳过费用阶段；没有重调模型代码。 |
| 未知证据 | models.py:56–73 与 costs.py:24–43 共用身份/版本/时间/未完成状态校验；calling/unknown 不得携带冻结金额进入消费。review.py 提供只读状态，不把 calling 宣称为模型仍在运行。未扩展评审 Owner 权限路由。 |

## 保留限制与建议（不冒充新增确定缺陷）

### L1：完成证据写入前失败会丢失本次可计算金额，calling 没有自动闭环

- 位置：chat/generation/invocation.py:79–87；persistence/generation/costs.py:24–27、81–85；chat/generation/discovery.py:42–46。
- 可复现条件：provider 已返回文本，让 store.complete 在执行 Redis 写入前抛 ConnectionError。随后恢复 Redis 并扫描。
- 本轮探针结果：模型调用 1 次，回复文本仍返回，GenerationResult.cost_status=unknown；持久记录为 calling/not_ready，无 amount_json；扫描不加账。不能因为应用一度拿到回复，就声称金额已持久化或以后必能自动补齐。
- 与“写成功但响应丢失”区别：后者 Redis 已有 completed，扫描可以消费；前者没有金额证据。当前不猜测金额、不重调模型符合未知结果安全边界。
- 建议：维持证据保留，待开发者确定阈值后对长期 calling 做仅分类的 CAS 处理，并继续允许原 token 晚结果收尾；分类本身不能恢复丢失金额。若要求这类已知输出也可最终计费，需要另行设计同 attempt/token/冻结金额的可靠完成证据交付，不能靠重做 provider 修复。
- status.md 已明确长期 calling 阈值待答复，本评审没有替开发者选择 120 秒或 5 分钟。

### L2：永久终态记录参与每轮扫描，补费时延随历史规模增长

- 位置：chat/generation/discovery.py:27–28、36–46；persistence/generation/costs.py:81–85；plugins/chat/recovery.py:70、94–97。
- 条件：大量 complete/unknown 历史键仍永久保存，新 pending 记录即时消费失败，需后台扫描发现。每个合法 ID 即使得到 not_claimed 也占用本页最多 3 条 outcomes 的配额。
- 可手工复现：替身 SCAN 返回按 ID 排序的三个 complete 键和第四个 pending 键；首轮只访问前三个，下轮才访问第四个。静态推导每 30 秒最多检查 3 个合法 generation ID；假设单进程、没有其他延迟，遍历 100,000 个此类键至少约 11.6 天。这是规模推导，未做生产负载测量，也不表示每条待办固定等待该时长。
- 建议：为可消费费用维护可恢复的待办/到期索引，完整证据仍永久保留；或明确允许的恢复时延及规模预算。不能为了扫描性能删除幂等证据。当前无恢复 SLA，故列为容量风险，不将其判作已经发生的漏账或重复扣账。

### L3：计费范围与保留口径有限

- 费用是字符费率估算，不是供应商 usage/账单；模型失败可能已产生供应商费用，unknown 不能推断为零。
- effects/store.py:78–85 的日期目标使用 172800 秒计数器 TTL，永久 generation/receipt 不等于永久每日汇总。超出汇总保留期后不能把日计数器当完整历史账本；本轮跨日测试没有模拟真实等待两天或过期后重建汇总。
- 不提供并发预算预留；不覆盖工具、检索、图像等其他模型调用。本项也不证明 Redis 崩溃持久性、主从切换或数据丢失后仍可防重。

## 本轮执行的定点验证

环境：`..\.refactor-snapshots\validation-py310\Scripts\python.exe`。通过 stdin 启动 pytest，设置 PYTHONDONTWRITEBYTECODE=1、禁用 pytest cacheprovider，并在测试导入前设置 Settings.model_config['env_file']=None。连接守卫拒绝非回环 socket.connect；不启动 NoneBot 或生产定时任务。

Redis 复用 `test.autonomy.test_pending_atomic.isolated_redis`：随机回环端口、临时目录、无 AOF/快照，并核对 server process_id 等于新建子进程 PID。结束关闭客户端和该子进程，不连接或清空既有 Redis。

实际结果：**12 passed in 15.79s**，仅以下选择，不重复整套：

- test_invocation：test_unconfirmed_admission_never_calls_provider（三参数）、test_failed_or_cancelled_provider_keeps_unknown_without_retry（两参数）、test_cancelled_admission_thread_cannot_later_invoke_provider。
- test_cost_worker：test_concurrent_workers_charge_frozen_date_once、test_target_response_loss_uses_receipt_on_retry。
- test_provider：test_engine_provider_persists_before_call_and_disables_sdk_retries、test_fact_check_is_a_separate_tracked_invocation、test_deferred_cost_is_discovered_without_second_provider_call。
- test_recovery_adapter：test_recovery_job_retains_failed_action_cursor_after_reminder_page（AST 提取实际函数；不是启动生产 scheduler）。

另执行两个内存脚本探针，断言均通过，不写入测试文件：

1. 真 AsyncOpenAI + MockTransport 返回 500，经实际 call_recorded；输出 `SDK500: requests=1; persisted=unknown; MockTransport only`。
2. 真 GenerationStore.start + complete 写前异常 + 单次合成 provider，再运行 GenerationCostScanner/inspect_generation；输出 `COMPLETE_WRITE_FAILURE: calls=1; reply preserved; calling/not_ready; no frozen amount; scanner does not charge`。

未重跑全项目、全 G1 或 Python 3.13 测试；未做真实模型、QQ、生产网络、生产 Redis、供应商账单核对或部署。历史文档测试数字仅作背景，未计入本轮结果。

## 交接

本项没有业务修复或待合并补丁；仅增加本报告。后续综合需保留 L1–L3，区分“禁止重复调用/扣记已有证据”与“所有未知费用均能恢复”。主 Agent 的发送回执集成及其他串行分项不在本报告验收结论内。
