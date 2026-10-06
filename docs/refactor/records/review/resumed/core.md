# R9 / R10 / R11 核心接入独立评审

## 范围与开工依据

- 评审日期：2026-09-09；本轮约束、源码与探针核对截至 22:01:49 +08:00。
- 实测 HEAD：`8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9`；评审对象为该基线之上的未提交工作区。
- 已读根 AGENTS.md、docs/agent/project.md、development.md、docs/refactor/plan.md、modules.md、status.md；`rg --files -g AGENTS.md` 仅找到根说明。
- 用户授权独立只读评审；唯一可写路径为本文。未改业务、测试或状态文档；未读真实 .env、聊天、画像或日志数据，未启动应用、发 QQ、部署或提交。
- 覆盖 plugins/chat、services/chat/pipeline、plugins/autonomy、services/autonomy；仅为接入核对阅读 bootstrap 和迁出的渲染函数。不评审其他评审者负责的存储实现、生成/工具/检索内部、Dashboard 或打包。
- 保留契约：会话串行、同发送者批次、治理准入、工具→上下文→生成→发送→提交、Owner 私聊授权、白名单、审批/取消、冷却与去重、单一 matcher/job 注册。
- status.md 的通过记录仅用来避开重复整套测试，不作为本人通过依据。Python 3.10.20 全套执行由主 Agent 负责。

## 结论

**本范围未发现可确认的结构重构新增行为回归；不能据此宣布防刷屏已具备或全项目已验收。**

独立对比发现三项需要后续处置的基线既有问题：两项通过基线/当前对照异步探针复现，一项有发送/提交源码证据。优先级均为 P2，建议在防刷屏行为开发中单独修复和验收，不把既有缺陷算作结构拆分引入。

## 覆盖与独立证据

| 链路 | 本人核对结果 | 证据边界 |
| --- | --- | --- |
| Chat ingress | 文本/媒体规范化、昵称、私聊 directed、管理员标志及起始时间保留；批次沿用最后一条输入和 transport、最早时间 | 逐段对照 git show 原 chat.py 与 ingress.py |
| 批次/锁 | key 仍为 session+user；短文本 <=80、无图/音/表情且 debounce>0 才合并；版本淘汰、合并后再取 session 锁，锁覆盖完整处理 | 原 handle_chat 与新 ChatWorkflow 对照；取消缺口见 F2 |
| 准入/路由 | 治理→必需 LLM→参与概率/节奏→有条件记录→边界回复→提醒→关系吸收顺序保留 | admission.py、workflow.py 对照原 _handle_chat_locked |
| 工具/生成/发送 | 工具→上下文→预算→generate→延迟→主回复→mark_sent→额外消息→commit→consume_cost 顺序未变 | AST 去掉显式依赖及 transport 适配差异后，仅剩管理员标志由 ingress 预计算；该表达式人工核对一致 |
| 聊天异常/取消 | 普通错误/超时仍反馈；CancelledError 不被 Exception 吞掉；execute 的 finally 清理工具文件 | 本轮合成取消探针：取消传播、cleanup=1、notice=0、reply=0、commit=0；未覆盖 to_thread 已开始后的副作用终止 |
| 聊天命令/发送适配 | 四个命令名/别名/优先级、私聊记忆限制保留；提醒六个函数 AST 完全相同；群回复与 fallback 保留 | chat_delivery 整体 AST 不相同是 render_group_text 迁入 utils/rendering.py，函数正文人工核对一致 |
| 自主模型/状态/策略 | 四种数据类、TTL/冷却、目标推断、白名单、审批阈值和内存状态初始化保留 | 只审自主状态接口与调用；底层持久化正确性不在本评审范围 |
| 自主规划/执行 | 提示词、模型调用/超时/失败静默、询问 Owner、发送前权限/冷却/去重/预算以及发送后的状态顺序保留 | 自主函数 AST 对照 44 个相等，见下文方法限制 |
| Owner 授权 | 注册 rule 仍要求 enabled、PrivateMessageEvent、owner_id 相同；白名单/批准/取消进入该 rule；process_owner_private 本身不重复鉴权，与基线相同 | 未发现外部调用绕过 rule 的新增入口；辅助函数不能单独当公共授权 API 使用 |
| 审批 token | pending_id 仍为 UUID hex 前 8 位；批准/改写/取消仍针对 latest，命令不绑定 token；取消先删除，批准在 send_action 返回后删除 | 正常串行语义保留；并发问题见 F1 |
| 注册唯一性 | chat on_message 一处 priority=40；自主 on_message 一处 priority=9；scan job 一处 id=mako_autonomy_scan，间隔和 last_scan_at 防重入保留；服务无 matcher/job 注册 | 静态完整扫描及入口导入链核对；未独立启动真实 NoneBot/Scheduler 验证热重载或多进程注册 |

自主 AST 方法：直接读取 `git show <基线>:src/plugins/autonomy.py`，逐个对应当前类方法/函数；去掉类型注解与装饰器，归一化 self/ctx 的显式依赖、repository/policy 调用及新增 ctx 参数。44 个函数归一化后相同；其余 3 处为 scan 的 `ctx=context` 和插件两层委托，人工核对。装饰器和构造器另外人工检查，AST 相同不是运行时依赖等价的完整证明。

## F1 — P2：审批与发送之间没有原子认领，重复批准及取消竞争

- 位置：`src/plugins/autonomy/owner.py:48-66`；`src/services/autonomy/execution.py:109-115`。
- 触发：第一条批准已读取 pending，通过冷却/去重并 await 发送；在其返回前，第二条批准读到同一 pending。成功状态和 pending 删除均尚未发生，第二条也能发送。同目标 scan 与 Owner 执行亦未见共享发送锁。
- 另一触发：第一条批准等待发送时收到取消，取消删除 pending 并回复“先不说”，第一条发送仍可完成；该回复给出错误的取消保证。
- 本轮真实源码合成探针：发送替身用 Event 暂停；基线和当前各运行双批准及批准→取消。两版双批准均调用发送替身 **2 次**；两版取消删除后原发送仍完成 **1 次**。没有真实 QQ 请求。
- 根因属于基线已有：基线 process_owner_private 同样在 await send_action 后删除，send_action 同样在 await bot.send 后设置冷却，没有 pending 认领状态。
- 修复建议：以 pending_id 原子认领状态；同目标共享串行发送/配额边界，将冷却与去重重查放进该边界。取消必须针对具体 pending 与执行状态；请求已交给外部传输时明确“已发送/发送中无法保证撤回”，不能假称成功取消。不要简单提前 delete 而丢失失败状态。
- 验收：同 pending 双批准只执行一次；批准/取消两种交错结果明确；scan/Owner 同目标并发受控；发送失败可追踪且不盲目重发。

## F2 — P2：防抖等待取消留下批次，已取消文本混入下一条

- 位置：`src/services/chat/pipeline/workflow.py:41-53`。
- 触发：文本写入 _pending 后，在 `await asyncio.sleep(delay)` 期间任务被取消；该等待没有异常清理。下次同 session/user 文本把残留 texts 与旧 started_at 合并。
- 本轮基线/当前探针：启动“cancelled”输入，yield 一次确保已登记，然后 task.cancel 并 await；残留 pending 数均为 **1**。再提交“next”，两版最终输入均为 **cancelled\nnext**。
- 影响：取消不表示候选被丢弃；未来防刷屏若直接取消 handler，会在后续恢复已淘汰内容。残留也可能长期持有输入/transport。
- 属于基线已有：原 handle_chat 的 sleep 与 pending 删除之间同样没有取消处理。
- 修复建议：取消时在 guard 下按 key+版本/所有权清理；不能无条件 pop 而误删更新批次。F1 迁移候选生命周期时明确旧任务取消是否保留新批次中的内容，避免版本号复用导致旧 sleeper 错认新批次。
- 验收：最新任务取消不残留；旧版本取消不删除新版本；取消后再发不会混入旧文本或时间；锁等待及生成中取消各自释放资源。

## F3 — P2：消息已经发送后，后续失败可能漏提交或保留可重试审批

- 位置：`src/services/chat/pipeline/execution.py:147-163`；`src/services/autonomy/execution.py:109-115`；`src/plugins/autonomy/owner.py:58-66`。
- Chat 触发：主回复成功，额外消息失败或等待被取消；历史 commit 和 consume_cost 尚未运行。另一路 commit 抛异常会被捕获，但后续审计仍写“已发送并提交历史”。
- 自主触发：bot.send 成功后 consume_cost 抛异常，冷却/去重尚未保存；异常传播导致 Owner pending 未删除，重试批准可能再次外发。
- 证据：本轮独立 git show 原 _handle_chat_locked/send_action/process_owner_private，与当前顺序一致；这是静态可达路径，本轮未注入该阶段异常，不声称动态复现。
- 修复建议：记录主发送事实与附件状态，分离发送成功、提交失败及未知传输结果；成功发送后的审批进入已发送待补记状态，不重新外发；审计摘要按实际提交结果产生。同步 to_thread 已开始时取消 await 不能撤销后台写入，需纳入一致性设计。
- 验收：主消息成功但附件失败、费用写入失败、历史提交失败均保留准确状态；重试只补提交，不重复发送。

## 探针与限制

- 本轮使用 `../mako-bot/.venv/Scripts/python.exe -B -`，实测 Python **3.13.5**。探针经 stdin 执行，只用标准库/合成替身，通过 AST 提取实际函数与类执行，不导入插件/runtime，不解析设置或访问 Redis/模型/QQ；未落盘测试脚本或缓存。
- 双版本负向探针共 6 场景（各版本：批次取消、双批准、批准/取消），断言均验证了上述缺陷；另 1 个当前 execute 取消传播/清理探针通过。缺陷探针通过不等于产品行为合格。
- 提醒六函数 AST 对照通过；自主归一化 44 函数对照通过；Chat execution 残余管理员参数差异人工确认。一次辅助脚本因 Windows 默认 GBK 读 UTF-8 失败，显式指定 UTF-8 后重跑完成；不计第一次为通过。
- 阅读现有 test/chat/test_chat_workflow.py 与 test/autonomy 的边界断言以确定缺口；未重跑这些测试、未重复整套 pytest，不引用主 Agent 的测试结果作为本人运行证据。
- 本轮没有真实 OneBot 事件分发、Scheduler 启停/热重载、多进程锁、Redis 恢复、模型超时联调或 Python 3.10 运行证据。注册唯一性结论限于静态入口，不扩展为部署保证。
- 未发现独立的“任务完成状态”新增注册/推进路径；R11 的完成仍是返回 sent/asked/rejected/silent 及审计事件，不能宣称发送与持久任务原子完成。
- 交接：结构评审可按“未发现新增回归、附基线缺陷及限制”纳入总评；防刷屏实现应纳入 F1/F2/F3（本文发现编号，与总体计划 F1 区分），完成修复后再独立验证。本评审不修改业务实现。
