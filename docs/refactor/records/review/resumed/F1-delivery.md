# F1b/F1d 发送调度与提醒独立评审

## 结论与开工边界

结论：发现 3 项 P2 可复现缺陷，建议修复后针对性复审；本范围暂不通过。未修改业务代码。

- 读取时间：2026-09-14 19:05–19:12（Asia/Shanghai）；模块 F1b/F1d。
- 已读取 AGENTS.md、docs/agent/project.md、docs/agent/development.md、docs/refactor/plan.md、modules.md、status.md，以及 F1b/F1d 实施记录。文件清单检索未发现下级 AGENTS.md。
- 授权：本次用户明确要求恢复独立只读评审；唯一允许写入路径为本报告。没有更新状态文档、测试或其他报告。
- 工作区：D:/vscode workplace/fun/bot/mako-bot-refactor；HEAD 8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9，存在大量既有未提交重构改动；评审对象是当前文件而非仅 HEAD。
- 保留契约：同目标串行、所有类别共享配额、失败不确认完成、提醒成功后才删除、资讯成功后才记录；不改变持久化格式或外部权限。
- 验证范围：三个指定文件、提醒领域/去重依赖及现有相关测试；实际运行 3 个受控探针，未重复全套测试，未启动应用、真实 APScheduler、Redis、模型或 QQ；未读取 .env 或真实数据。

## F1-D1 [P2] 取消未使排队中的提醒失效

位置：src/plugins/chat/reminders.py:40–43、167–174。

到期回调将内容作为参数快照送入 dispatcher，却没有传入 guard，也不检查该 job 是否仍有效。DELETE 删除调度任务和提醒记录后，已经进入 dispatcher 等待间隔/配额的回调仍然发送旧内容。移除 scheduler job 不等于取消已启动的协程。MODIFY 同样没有使旧回调失效；同 ID 更新时，旧回调成功后的 remove 还可能删除新版记录。

复现：建立 spacing=0.06 的真实 OutboundDispatcher，先用 command 消耗一次间隔；启动实际 send_group_reminder 函数使其排队；再调用实际 handle_reminder 的 DELETE 分支，scheduler.remove_job 替身抛出“date job already removed”，模拟已触发的一次性任务；最后让队列继续。实际输出：取消回复调用 1 次，旧提醒发送 1 次，remove 调用 2 次。删除发生在发送之前，仍未阻止发送。

建议：维护提醒有效性/版本，在 dispatcher 最后发送检查处验证 job 仍存在且版本匹配；成功后采用版本匹配删除，避免旧执行删除新记录。取消与已经开始的外部发送须区分：已经在发送的结果可能未知，不能无条件宣称取消完成。

验证边界：执行实际函数体和实际 dispatcher，存储、消息构造、解析器、scheduler 与回复为替身。取消回复替身即时返回，不能据此断言生产环境“取消回复先到、提醒后到”；生产回复也经过 dispatcher 且优先级低于 reminder。确定的问题是取消状态已提交后旧回调仍会发送。未运行真实调度器；同 ID 修改删除新版是代码路径推导，未作为额外实测结果。

## F1-D2 [P2] 修改保留的到期提醒会部分成功并留下旧记录

位置：src/plugins/chat/reminders.py:180–193；相关保留策略：40–42、97–100。

F1d 特意保留未确认送达的到期记录。此时旧 date job 已不在调度器中。MODIFY 先调用 _schedule_reminder 创建并保存新提醒，再 remove_job(old)。旧 job 不存在时跳到 except，后面的 reminder_book.remove(old) 永远不执行。用户收到失败提示，但新任务已经创建，旧记录仍在。按提示再次修改旧记录可以继续产生新任务，导致重复提醒或列表与实际任务不一致。

复现：ReminderBook.find 返回到期 old；解析器返回 MODIFY 及未来时间；_schedule_reminder 替身返回 new；remove_job(old) 抛 LookupError 模拟任务不存在。执行实际 handle_reminder：新调度调用 1 次、旧记录删除 0 次、错误回复 1 次。

建议：针对 JobLookupError 将“不存在的旧调度任务”视为已移除，继续清理旧记录并确认更新；其他异常应有明确补偿或部分成功状态，避免创建完成后笼统报失败。结合 D1 的版本检查处理已执行/排队中的旧回调。

验证边界：本探针验证控制流，不验证 APScheduler 真实异常类型或持久化事务；_schedule_reminder 的“注册后保存”顺序另经 69–86 行静态核对。原顺序问题可能早于 F1d；本轮未对原始基线作归因，F1d 的保留到期记录策略使其成为正常恢复路径。

## F1-D3 [P2] 等待期限未覆盖取得目标锁的等待

位置：src/services/delivery/dispatcher.py:78–90、107–119。

deadline 在入队前计算，但 async with state.condition 没有超时；只有获得锁后才检查 deadline。前一请求的 guard/send 持有该锁，后续 reminder/command/chat 即使已经超过 required_wait/chat_wait 仍无法返回。尤其配置 required_wait 小于 send_timeout 时，可明显突破承诺的有界等待；多个排队者还要依次拿锁才能发现自己已过期。配额本身不会因此被绕过，但调用者及其上层锁会被额外占用。

复现：OutboundDispatcher(spacing=0, required_wait=0.02, send_timeout=1)；首个 command 的发送回调等待 asyncio.Event；第二个 reminder 入队。0.06 秒后第二个任务仍未完成（已达预算 3 倍）；释放首个发送后才返回 False。探针断言成立。

建议：让取得 condition 锁也受剩余 deadline 约束，并保持取消/超时后的 ticket 清理与唤醒正确；定义 wait=0 的立即尝试语义。增加一个锁被长发送占用时的期限断言即可，不需重跑无关测试。

验证边界：实际 dispatcher、真实 asyncio、短时间预算；send_timeout 仍限制合作式回调，不把该问题描述为默认配置下必然无限等待。

## 配额、确认及消息丢失/重复核对

- dispatcher:96–106、135–155：类别配额共享全局 attempts；失败发送仍计数；guard 拒绝不计发送预算；最后一次 API 返回后重新计算间隔。未发现这里可直接绕过共享配额的路径。
- dispatcher:140–158 的 True 表示回调正常结束且结果不为 False，不等于收件人已读或端到端 exactly-once。超时/取消可能发生在外部已接受之后，不能据 False 断言“绝未发送”。
- reminders:40–43 仅 True 后删除；失败保留及启动跳过过期任务是 F1d 明示策略。未送达但仍保留的记录没有自动补发，不能将“保留”写成“保证最终送达”；本轮不把已明确延期的自动重试单列缺陷。
- scheduler:64–78、177–178、189–190 只在 True 后写已发记录/资讯指纹，失败不会直接标已发。发送与这些存储操作不是原子事务；发送后取消/存储失败可能留下未登记的已发内容。去重 check 在目标锁外，record 在发送后；未实测并发去重竞态，不将其列作已复现新增缺陷。后续如要求跨取消/重启的防重复保证，需单独设计发送结果未知状态与补记。
- 现有 test_outbound_dispatch.py 覆盖正常配额、排队取消等；test_sender_acknowledgement.py 覆盖布尔成功/失败和到期记录保留，但未覆盖上述三个交错/部分提交路径。仅阅读这些测试，本轮没有宣称它们重新通过。

## 实际验证记录及快照

Python 3.13.5，复用 ../mako-bot/.venv/Scripts/python.exe，以 -B 和 stdin 执行，无探针文件或字节码落盘。dispatcher 由 runpy.run_path 执行（只含标准库导入，未调用配置加载）；提醒函数由 AST 提取，去掉注册装饰器并注入受控替身，避免生产初始化。

第一次探针执行已确认 D3，随后 AST 构造缺少 lineno 导致测试脚手架 TypeError；使用 ast.fix_missing_locations 修正内存脚手架后，仅补跑尚未完成的 D1/D2，退出码 0。没有把脚手架失败当作业务缺陷，也未重复执行 D3。

复现参数与交错顺序已逐项列出；探针仅检查对应事实，不证明整条生产链路或 Python 3.10 兼容性。本轮未运行全套 pytest、编译、打包、真实服务或联网验证。

评审时 SHA256：

- src/services/delivery/dispatcher.py：EA84F7BA907E663AF7AF31770A4B2B4B531E74C58E509B2DE0C42ACD51FCACE4
- src/plugins/chat/reminders.py：F4CD5B7263FCB6D1827F97CCC9501AFF414CC573CE1F5764317B4C6106973E22
- src/plugins/scheduler.py：0809B8BF0E09471BDDAA655F56FB24983A972DD55C1D6D19A25B9F860D769F21

以上结论只对应此快照；未修复业务，不扩大为 F1 全部模块的评审结论。
