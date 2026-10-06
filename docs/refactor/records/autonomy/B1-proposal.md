# B1 审批执行状态方案（2026-09-16 已批准）

2026-09-16。依据当前 owner.py、execution.py、repository.py 和 R16 conclusion.md。
本文件是方案，不表示业务实现或独立评审通过；config.py 不拆分。

## 已确认的问题

- Owner 读取 pending 后 await 发送，期间另一个批准可读取同一 pending。
- 取消只删除 pending，发送 guard 不检查 pending，排队消息仍可能发送。
- dispatcher 的 False 同时表示未开始和外部结果未知，不能直接据此允许重试。
- 删除 pending 使用分离的 GET/DELETE，旧操作可能删除新 latest 指针。
- Redis 读写失败会回退内存，不能以该方式实现跨实例互斥。

## 推荐范围与存储

保留 PendingAction JSON 与现有 key，新增 autonomy:execution:{pending_id} 状态记录。
字段：schema_version、state、claim_token、updated_at、目标与批准内容摘要。
原始批准内容沿用 pending，不在执行状态复制私人正文；发送前校验摘要匹配。
Redis Lua 原子核对并转换状态；同一 pending 仅一个 token 能认领。
本方案提供防重复尝试，不承诺 OneBot 外部效果 exactly-once。

| 状态 | 允许的动作 |
| --- | --- |
| 无状态且 pending 有效 | 原子认领为 queued；并发批准只报告处理中 |
| queued | 在原子 guard 中进入 sending；取消可原子转 cancelled |
| sending | 已进入外发边界；取消只能报告可能已送达，不再删除执行证据 |
| sent | 禁止再次外发；清理 pending 与补记失败不改变此状态 |
| unknown | 禁止自动或重复批准重发；需人工核对 |
| cancelled | guard 拒绝，禁止再次批准原 pending |
| rejected_before_send | 明确未进入外发边界，可由下一次显式批准重新认领 |

queued 因任务取消或超时退出，只在 token 匹配且仍 queued 时释放。
进程崩溃留下的 queued 可在租约到期后重新认领，旧 token 无权转 sending。
sending 租约到期只能视作 unknown，不允许抢占后发送。
外发成功但写 sent 失败仍告知已送达，并保留 sending/unknown 阻止重发。
未调用传输适配器前的拒绝与传输开始后的异常必须区分，不能仅凭 bool。
latest 指针清理使用 compare-and-delete，与新 pending 创建并发时保留新指针。

## 必须由开发者选择的运行策略

推荐：审批发送要求 Redis 状态可读写；不可用时保留待办并暂停审批发送。
这会改变当前 Redis 故障时仍可内存执行的可用性，但避免双实例或重启后重复发送。
备选：明确单进程内存模式，界面和日志提示重启后不保证防重复；不得静默切换。
未知记录不自动清除；已结束记录可在 pending 失效后清理，旧 pending_id 不复用。
后续提供 Owner 核对指令：标记已送达或放弃；重新发送必须另建待办并明确提示重复风险。
不在本模块引入自动重试、全局发件箱或历史/费用幂等迁移。

## 分工与验收

1. 存储单元：原子状态转换、token fencing、latest 清理、故障时关闭审批出口。
2. 编排单元：Owner 命令、排队 guard、传输阶段区分、取消和未知反馈。
3. 综合评审 Agent：检查两单元契约、崩溃窗口、资料真实性及测试遗漏。

必要验证仅覆盖：双批准、排队取消、发送中取消、旧 token、旧 latest 清理、
Redis 状态写失败、传输超时、送达后补记失败；用受控替身，不发真实 QQ。
Redis 原子脚本必须额外通过隔离 Redis 集成验证，替身通过不算该项完成。
尚无可用独立 Agent 新结论；此前额度失败不能算完成以上分工。

修改路径预计为 services/autonomy 的审批状态领域模块、repository/execution、
plugins/autonomy/owner.py、对应测试与说明。新建文件前检查目录直属文件数。
回退需先停止新审批并处理 sending/unknown，不能直接让旧代码忽略状态继续发送。
