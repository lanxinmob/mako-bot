# H1 Owner 人工核对接线

2026-10-05 23:35 +08:00，恢复前重读AGENTS.md、project/development、plan/modules/status、B3及H1d和关联代码；HEAD仍8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9，保留全部未提交草稿。依据H1d Owner范围及已批准的未知时间政策、发送侧5分钟分类，不重新索要同一批准。

允许修改history_commit/reconciliation.py、delivery.py/delivery_scripts.py及task解码必要分支；plugins/autonomy/history_owner.py、delivery_owner.py和history_delivery/review.py；专属测试与本说明。Locke租约分项23:38完成并交付effects.md；23:41恢复后再次重读AGENTS及六文档/批准和关联代码，随后才修改delivery/tasks依赖，原报告仍绑定其原哈希。

人工已送达：仅unknown可转换；保存操作者字符串、核对时间及结论，不写虚假delivered_at_ms，两项历史保持needs_review。人工放弃保存abandoned并解释不等于未送达。重复相同结论保留原记录；相反结论或原调用晚ACK拒绝，不能恢复begin。Owner查询仍只读，不自动分类、补记或发送。

格式沿H1版本1增加严格人工来源分支；只有sent/abandoned和匹配结论/操作者/核对时间/两项保守状态才可解码，缺字段或任意伪造任务状态待核对。原传输确认与历史租约格式保持；旧记录缺confirmation_source视为transport。更旧版本不理解人工状态时应故障关闭，上线/回退仍须停旧进程、保留证据。

检查范围：真实Owner鉴权和关闭自主功能的接入、双结论竞争、写后响应丢失、晚ACK与人工结论竞争、缺少实际时间不激活消费者、坏人工字段/意外TTL关闭；只运行新增及受本次共享解码影响的必要点，不复跑全部基础项。

人工命令已接线：Owner私聊“聊天历史核对 <64位ID> 已送达/放弃”。共9个新增检查及1个共享解码影响的原传输激活节点，Python3.10 10通过（13.14秒）；没有全套、真实QQ或模型调用。随后严格补上人工记录必须显式保存null时间和来源/字段异常矩阵，修改节点及两项原Owner查询3通过（5.81秒）；Python3.13定向compileall与git diff --check通过。独立入口/Owner评审未完成，不声称上线。

新增实际恢复扫描两种人工结论均不改全库DUMP、不激活历史，以及prepared/活跃sending不能人工结束，3通过（4.24秒）。共12个新增节点各有通过证据；旧基础仅按共享解码影响运行1个激活节点及2项只读Owner查询，没有为等待Agent重复整套。

使用边界：状态/列表命令只查询，主动功能关闭仍可访问；核对命令不主动把sending分类unknown，也不接受实际时间输入。5分钟分类来自有界恢复扫描，不保证正好第5分钟可人工核对。人工结论一旦写入，原调用晚ACK被拒绝并保留该事实；需另行核查的时间证据不能通过清除人工字段或重发消息补齐。

第二分项entrypoint.md已独立核对人工分支及入口，未发现此范围新增P1/P2，完整分项因恢复E1暂不通过；probeB建议的Owner先赢旧ACK/读后TTL已固化3项，通过（4.91秒）。H1-recovery-errors.md记录后续E1修复及综合额度中断；仍不能据本Owner检查称完整H1验收。
