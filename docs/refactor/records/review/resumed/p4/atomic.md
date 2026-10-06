# P4 存储原子性独立只读评审

## 开工与边界

- 读取与核对日期：2026-09-24；报告核验时间 11:35，Asia/Shanghai。
- 模块：已批准 P1–P6 中的 P4 存储基础；配置拆分暂停。
- 已重读：根 AGENTS.md、docs/agent/project.md、development.md、
  docs/refactor/plan.md、modules.md、status.md；并核对 records/chat/B3.md。
- 仓库内 AGENTS.md 搜索仅发现根说明，没有目标路径下的追加要求。
- 工作区：D:/vscode workplace/fun/bot/mako-bot-refactor。
- HEAD：8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9；本次评审对象为工作区新文件，非仅 HEAD。
- 唯一持久化写入路径：本报告。未修改业务代码、原测试、配置或原 mako-bot 目录。
- 保留契约：Redis 故障关闭；正文/revision/调度意图共同转换；旧快照不能取消或完成新版本；
  未知送达不自动重发；取消和替换保留旧执行证据；不以存储完成代替适配器接线。

## 结论

在下述四个文件、正常 API 输入和本次受控故障模型内，**未发现可确认的原子转换或竞态缺陷**。
该结论不是整个 P4 验收：当前只有存储基础，没有提醒适配器接线、调度恢复或真实 QQ 验证。
不将实现方此前的测试结果记为本评审者实际执行的结果。

## 静态核对

以下行号相对于本报告记录的文件快照。

| 位置 | 核对结果 |
| --- | --- |
| src/services/persistence/reminder_state/models.py:15–31 | 快照保留原始正文及 revision，摘要取原始字符串；未用重新序列化后的正文替代 CAS 输入。 |
| src/services/persistence/reminder_state/scripts.py:5–20 | 三个源 hash 的类型和已有 intent 的基本结构均在任何写入前检查。 |
| src/services/persistence/reminder_state/scripts.py:33–41 | 非创建操作匹配原始正文和 revision；完成的幂等回执还绑定旧 revision、动作键和完成原因。 |
| src/services/persistence/reminder_state/scripts.py:43–65 | 动作键读取及结构检查在源写入前；完成证据绑定 kind、业务 ID、bot、目标、revision 和源摘要；过期 sending 返回 unknown。 |
| src/services/persistence/reminder_state/scripts.py:67–80 | 创建/替换/迁移在同一 Lua 执行中写入正文、revision 和意图；迁移拒绝已版本化项及过期项。 |
| src/services/persistence/reminder_state/scripts.py:81–88 | bot 绑定检查当前 intent，不允许另一 bot 通过同一旧快照覆盖首次绑定。 |
| src/services/persistence/reminder_state/scripts.py:89–96 | complete 仅接受 sent；取消/完成删除有效源并留意图，不删除旧动作键或 revision。 |
| src/services/persistence/reminder_state/store.py:19–39 | Redis 异常封装为结果不可确认，不走内存回退；异常本身不能证明写入未发生。 |
| src/services/persistence/reminder_state/store.py:49–72 | 替换限制身份与所有者不变；取消/替换允许不传动作键，此时仅报告 uninspected，接入方不能据此声称未送达。 |
| test/delivery/state/test_reminder_source.py:31–159 | 已有测试涉及创建、错误意图键、双替换、排队/发送中取消、完成幂等、旧版本晚确认、错误源绑定及旧记录迁移；本轮只读，未重复运行。 |

取消先执行时，后续 begin_send 的源检查失败；begin_send 先执行时，取消仅失效源，不能撤回已开始的传输。
此顺序由相邻 delivery/state/scripts.py 的 claim/begin 源检查支持；它是依赖核对，不构成对整个 P1 的重新验收。
replace 产生新 revision 是显式修改行为，不能将其当作 unknown 的自动恢复或重试方式。

## 本轮实际验证

使用 ../mako-bot/.venv/Scripts/python.exe -B - 从标准输入运行新增临时探针；Python 3.13.5。
复用已阅读的 isolated_redis fixture，每组启动独立本机 Redis，核对进程 PID 后才写合成数据，结束后关闭进程。
未启动应用、调度器或 OneBot；未连接现有 Redis，未运行原测试集、全套测试或真实 QQ。
探针未保存为仓库测试文件；执行输出保存在本任务工具记录中。

四组共 **15 个新增场景全部通过**，命令 exit code 0，工具记录耗时 8.20 秒：

1. 键类型故障，6 个场景：分别将 reminders、REVISION_KEY、INTENT_KEY 设为 string 后 create；
   将动作键设为 hash 后分别 cancel、replace、complete。均抛 ReminderPersistenceUnavailable，
   比较所有测试键的 DUMP 值，调用前后完全一致。
2. 未知送达，2 个场景：正常 claim/begin 后将合成动作租约置 0，分别 cancel、replace。
   complete 先返回 not_confirmed；变更成功且报告 unknown，旧动作原始值不变、TTL=-1；
   旧动作无法再次认领；旧 token 的晚 sent 可记录，但旧 complete 不能清理替换后的源。
3. 完成竞态，3 个顺序：sent 后 complete→replace、replace→complete、cancel→complete→显式重建。
   只有当前源版本可变更；晚完成和重建后的旧取消被拒绝；每个顺序的旧 sent 证据保持不变。
4. 写入后响应丢失，4 个场景：包装客户端先执行真实 EVAL，再抛合成 ConnectionError，
   分别覆盖 create、replace、cancel、complete。上层均报告不可确认，但重新读取证实已提交；
   重建原 create 被拒绝、替换后的旧取消被拒绝、取消意图保留、重复 complete 返回 already_completed。

## 验证限制与接入要求

- 竞态探针覆盖 Redis 串行化后的指定顺序，没有做线程压力、双进程或全部交错穷举。
- 响应丢失是 EVAL 后注入异常；未模拟真实网络断连、Redis 崩溃、复制切换或磁盘持久性。
- Lua 原子执行不等于事务回滚；本次只确认所测键类型错误在写入前失败，不推广为所有资源故障下的回滚保证。
- 未知状态探针修改的是合成租约，无真实等待或 QQ 送达判断；提醒脚本只报告 unknown，未重写该动作。
- 本轮没有 Python 3.10 执行证据，没有 APScheduler 注册/恢复、生产调用方或跨进程 exactly-once 结论。
- 接入方必须使用同一持久化 revision 和 bot 身份、传入正确动作键进行状态反馈，并经 DeliveryStore 源校验后发送。
  可选 action_key 为空或不存在时的结果不能单独证明没有其他动作在发送。
- 旧证据保留已验证；有界查询/归档、人工核对及可靠补记属于后续工作，未在此实现或验收。

## 评审快照 SHA256

| 文件 | SHA256 |
| --- | --- |
| src/services/persistence/reminder_state/models.py | 13ac61ec04a4adde6ef331b6245ec1972e4f8ccb7e41060cbea0f1d49ca9efae |
| src/services/persistence/reminder_state/scripts.py | edc14cf41d009637777e917d4d170ee3fe29fdc2cf31fe63133d46ed8e0bc3fc |
| src/services/persistence/reminder_state/store.py | c9b3c8e260ed38788501fd1f5bfdd2e893f373d5493ff83196c087afb1c43148 |
| test/delivery/state/test_reminder_source.py | 5104ef8ff579ffb2e422f08a8fc424fbe5c6352f43b7715146e1abbcbe19bd69 |

报告共 85 行，该目录实际 1 个直属文件，满足 400 行/10 文件阈值；未改结构扫描器或其他报告。
结束时复核四个被评审文件 SHA256 均未变化。
