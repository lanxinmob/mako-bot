# H1d 历史效果租约、消费与恢复接入

2026-10-05 23:00 +08:00，恢复及开始本子模块前重新读取AGENTS.md、project.md、development.md、plan.md、modules.md、status.md及H1批准与基础代码。HEAD仍8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9，已有未提交草稿保持。依据用户明确采用H1和串行工作要求；不扩大B1、不拆config、不部署。

允许范围：persistence/history_commit/tasks.py、task_scripts.py及必要的状态校验；chat/history_delivery/的目标/消费者/有界发现；专属测试与本记录。开工时实际pipeline仍沿原历史提交；随后按同一批准方案接线，下面分列实际实现和验证。

保留契约：仅永久且已确认sent的冻结计划可原子认领两个独立任务。session/global各有稳定effect_id、租约token、Redis时间截止与退避；会话冲突只终结session为needs_review，不阻断global。目标采用原始快照CAS及既有永久全局回执，冻结ACK观察时间/时区/保留数不随重试改变。unknown不认领、不重发、不调用模型；取消等待线程时保留租约，旧token不能收尾新租约。

验证限新增故障与竞态：并发认领与响应丢失、线程取消、旧token隔离、会话冲突但全局独立、目标写后丢响应及ACK时间冻结；旧基础测试不重复。后台恢复和Owner需完整接线后再验收，未知实际时间按既定人工政策保留待核对。

租约、目标、消费和有界扫描已实现。首轮新增9项检查8通过1失败（14.30秒），失败为新测试误要求JSON字段顺序；核对冻结计划的规范排序后改为比较解析历史，补上全局目标丢响应；该项与新增发现3项共4通过（2.95秒）。共12项新增检查各有通过证据，未重复旧基础项。

继续同一批准H1d接入点：允许chat/models.py、pipeline/models/execution/completion、plugins/chat/ingress/delivery/recovery及专属测试。ChatServices显式注入默认历史运行时，读取确切快照、实际发送回调内begin、ACK观察立即冻结时间、sent原子激活、即时与周期消费者同计划；移除普通主回复旧commit直写。guard在Redis await后再次检查。相关生产路径仍须受控验证和独立复核，不能以草稿当成已上线。

开发者随后单独批准发送侧5分钟分类：sending超过300000ms时仅以合法快照/永久TTL/raw CAS改unknown，原token仍能晚ACK收尾；不重发、不激活历史、不改变冻结时间。分类接同一10键有界扫描，实际延迟取决于扫描进度。

Owner只读状态/列表已接原Owner私聊鉴权，展示目标、两个任务状态/尝试和固定原因，不展示正文/快照/token、不分类或认领。新增两个实际Owner适配器检查通过（3.81秒），含查询前后全库DUMP不变、非Owner/群拒绝与坏记录。沿同一H1d批准接入，允许chat/history_delivery/review.py和plugins/autonomy/history_owner.py、delivery_owner.py及专属子包测试。

人工核对已在第一项独立租约审查终态后接线，详见H1-owner.md。未知→人工sent时两项历史保持needs_review且delivered_at_ms=null；unknown→abandoned表示放弃后续处理，不推断未送达。永久记录保存操作者/核对时间/结论，重复同结论保留原字段；相反结论与晚ACK不得覆盖。人工来源字段严格校验，消费者显式拒绝人工来源；入口/Owner独立复核及综合尚未完成，不能以实现存在当成验收。

实际入口检查：completion/workflow/C2首轮23通过1失败（4.71秒），失败是旧context测试传输替身未显式返回True，修正后该节点与5个新增真实pipeline/隔离Redis场景共6通过（10.65秒）；随后begin等待后失效、sent写后丢响应及恢复不重发两项通过（3.63秒）。分类/发现/实际周期恢复/传输/插件导入共27项通过（50.24秒）。没有全套、付费模型或真实QQ；只根据目标风险扩大检查。

追加传输阶段隔离：已观察ACK后，适配器回调异常不撤销确认，也不触发普通失败notice；取消仍透传。新增真实adapter ACK后抛错的隔离pipeline检查通过（4.05秒），仍一次发送、两项历史完成且没有失败通知。发送事实与后续存储故障分开，不能用notice或重新发送修复补记。

人工核对接线期间补一个实际pipeline取消边界：adapter观察ACK后抛CancelledError，取消继续透传，但finally先保存原毫秒时间及sent/pending；实际HistoryScanner随后两项补齐，旧commit/QQ/模型均不重放、无失败notice，1项通过（3.08秒）。没有扩大生产异常策略或重复旧测试。

第一位H1d独立Agent Locke（01a10cab-ce03-7e13-9e24-55cd597a7f8c）23:38 completed，租约/目标/消费分项附限制通过，无新增P1/P2，报告review/resumed/history/effects.md绑定当时哈希。其P3建议随后串行固化5个实际package隔离回归，首次5通过（8.16秒），实现者验证不冒充独立评审，记录H1-interleavings.md。第二位Schrodinger（01a10cc8-d0dd-7242-a089-83abbd587397）入口/恢复/Owner分项completed，报告review/resumed/history/entrypoint.md指出E1，结论见后文；H1d综合尚未完成。

2026-10-06 第二分项已completed：E1/P2实际worker认领或收尾可用性故障被折叠为普通结果，Scanner返回成功下一游标、recovery推进，本分项暂不通过；证据保留与无重发不能替代故障不跳页。E2/P3建议固化Owner先赢stale ACK/读后TTL。独立probeA反例断言完成但Windows临时目录清理导致退出1，报告已说明及清理，不能算全程绿色；probeB退出0。McClintock串行综合新方案唯一报告review/resumed/history/delivery-synthesis.md，终态前不修改worker/discovery。

2026-10-06 11:16 McClintock权威终态为workspace out of credits，综合新报告不存在；未重启句柄。随后重读规范，在已批准H1内实施E1内部严格故障传播，13项修复后相关检查通过，E2另3项固化通过，具体方案/复现/限制见H1-recovery-errors.md；主Agent实施不代替综合评审，新分支仍未独立验收。
回退只反向本子模块补丁，保留所有plan/session/global永久证据，禁止用旧发送器重放新记录。
