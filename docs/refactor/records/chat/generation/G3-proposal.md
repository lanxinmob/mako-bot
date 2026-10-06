# G3 已知生成结果的完成证据交付提案

状态：2026-10-06开发者要求优先完成小鸟/传送/真实期刊，费用增强不再推进。本文件保留为未实施方案，不新增数据库或部署卷；旧独立关卡继续保留待办，不阻塞本次新功能开发。

## 开工与代码依据

2026-10-06 11:35 +08:00，重新读取根AGENTS、project/development、plan/modules与status当前批准及交接；核对B3、G1独立报告L1、现场invocation/provider/store/models/scripts/discovery/recovery、Dockerfile及Compose，仅根AGENTS。授权限只读调查及方案文档；允许修改本提案和状态入口。原草稿、暂停的config拆分与既有全部证据保留。

- invocation.call已经取得原始文本并算出金额，但store.complete写前失败后仍返回text/unknown；重启后本进程持有的金额丢失。
- calling/unknown没有amount_json，G2索引不能凭空恢复金额；五分钟分类只改状态。G1独立报告已用实际GenerationStore复现，本次不重复已通过探针。
- store.complete要求原spec/token与冻结金额；晚结果可以收尾unknown，已有completed金额冲突拒绝。成功响应丢失可用同金额重交完成证据，不能新建尝试、重新调用模型或直接加账。
- 当前Compose只有Redis数据卷和bot日志卷；应用容器的其他文件不能被本方案假定为持久卷。仓库没有生成证据的SQLite接口，新增属于存储格式和故障策略扩展。
- facts.validate_factual_answer目前捕获普通Exception并返回False；新增本地持久化阻断必须贯穿engine/facts/pipeline，以独立异常透传，不能被该fallback吞掉后继续发送另一份回答。此处只是G3接入约束，不声称原事实验证fallback是新增运行缺陷。

## 推荐方案与保留边界

新增本机SQLite完成证据仓库，Redis继续负责唯一模型调用授权和正式计费证据。只保存attempt_id、原spec_json、原token、冻结amount_json、状态/原因码/调度时间，不保存聊天正文、原始输出或API密钥。内部token按私密执行凭据保护，不放日志、Owner消息或Dashboard。

调用顺序为：本地预登记 → Redis首次start确认 → 本地绑定原token确认 → 调用一次provider → 按原始文本计算金额 → 本地冻结完成证据确认 → Redis.complete → 既有G2费用消费。局部注册和绑定不授予模型调用权；恢复入口不能执行start或provider。所有amount_json复用现有float/nonnegative序列化口径，不按新的费率、输出或日期重算。

本地登记/绑定失败时暂停该次生成，已经创建的Redis calling保留，不能自动续做模型。provider返回后本地冻结失败时暂停该次回复的后续发送，保留Redis未知证据和诊断；不退款、不声称零费用、不重调模型。调用失败/结果未知时只有无金额记录，不能根据预算推算账单。无提供商fallback不创建本地付费尝试。

本地完成冻结成功、Redis.complete不可用时允许返回当前文本，费用显示pending；本地记录保留到相同spec/token/amount的Redis完成得到确认。后续只重新交付同一完成证据，由原有费用目标和永久回执负责计费幂等；发送是否发生与费用恢复独立。确认后删除本地交付待办，不删除Redis generation或receipt；本地删除响应丢失只导致同证据再交付。

## 状态与恢复规则

| 本地状态 | 保存的证据 | 允许的操作 |
| --- | --- | --- |
| reserved | 原spec，无token/金额 | 仅原实时请求可继续首次Redis准入；后台不调用模型 |
| calling | 原spec/token，无金额 | 原调用可交付晚结果；超时仅分类待核对 |
| result_pending | 原spec/token/不可变金额 | 同一完成证据重交Redis.complete |
| needs_review | 原证据及固定原因码 | Owner只读核对；不猜金额、覆盖冲突或重建授权 |

重复保存同金额幂等，spec/token/金额不符转冲突；未知schema/损坏记录拒绝消费。Redis记录missing、错误TTL、身份/金额冲突等转待核对，不由本地凭据重建已丢失的Redis授权。Redis完成但索引更新未确认时保留交付待办，原G2修复仍可独立工作。

后台每30秒最多尝试3个到期完成记录，退避30/120/300秒、之后每300秒，有独立预算与异常隔离；调用未知项不占交付尝试预算。不可用时保留当前项，不越过未保存的结果；无效项记录固定原因后允许检查后续项。两个恢复器可以交付同一证据，依赖原Redis完成幂等，不以本地租约承诺Redis外事务。

取消保持原信号。本地写入线程已开始时不能删除其记录、释放所有权后假定写入停止；晚写入交由后续恢复发现。原provider晚结果仍用同token，不新建身份。启动恢复只处理已有result_pending，calling/保留的unknown不自动生成或计费。

## 配置、资源与部署边界

仅计划为Settings增加一个generation_evidence_path字段/公开环境变量GENERATION_EVIDENCE_PATH，默认data/generation-completions.sqlite3；不拆config.py。实施前确认新增后仍不超过400行，超标则停止提出局部方案，不能压行绕过。路径在启动时固定为绝对路径，读写失败拒绝模型准入，不能悄悄换目录或退内存。

本地使用回滚日志模式DELETE、synchronous=EXTRA，设置有限锁等待，并检查实际PRAGMA值。同步数据库工作在线程内创建/关闭连接，不跨线程共享同一连接；SQL使用绑定参数，事务原子绑定身份和金额。[SQLite同步规范](https://www.sqlite.org/pragma.html#pragma_synchronous)及[Python3.10连接接口](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.connect)支持这些实现约束。

登记前检查未解决条数，推荐4096作为停止新准入的水位。并发登记需同一事务检查；未知结果保留，不按期限删除来腾容量。晚结果优先保存，水位不能被描述为任何迟到结果下的硬容量上限。达到水位停止新付费调用并告知Owner核对，不能丢弃旧证据。长期记录/磁盘空间需运维监控，不能用“有界消费”声称永久证据的存储量也有界。

计划Compose新增bot-data卷挂/app/data，Dockerfile准备目录权限；本地数据库/日志附属文件均放该目录并加入.gitignore。卷要能跨容器重建保留，备份只用数据库一致性接口，不直接复制活动文件。部署文件修改可审阅，但实际部署/数据迁移仍需明确发布授权；不读真实.env或已有私密数据库。

SQLite不与外部provider形成分布式事务。拿到模型结果至本地提交之间崩溃/磁盘故障、供应商结果未返回、存储丢失仍可能留下未知费用；不能承诺所有付费调用最终自动结算。事务可靠性依赖实际文件系统和设备的刷盘语义，需保留[官方原子提交说明](https://www.sqlite.org/atomiccommit.html)中的前提。现有费用仍是字符估算，不改成供应商真实账单。

## 串行实施与评审单元

| 单元 | 允许的主要路径 | 契约和必要验证 |
| --- | --- | --- |
| G3a 本地证据 | persistence/generation/completions/及独立测试子包 | 同身份/金额绑定、事务冲突、数据库重开、坏版本/锁超时、并发准入水位、取消后晚写 |
| G3b 生成交付 | chat/generation/invocation.py、provider.py、完成交付适配、engine/facts及pipeline阻断异常接线、专属测试 | 保存失败前不调用provider；取得已知文本后本地写失败暂停回复且不被事实fallback吞掉；Redis写前/写后丢响应与单次调用；主回复/事实检查各自身份 |
| G3c 恢复与运维 | chat/generation完成worker、chat/recovery、Owner只读生成查询、单一路径配置、公开部署示例及文档 | 重开后同金额完成、费用一次、跨日、无provider/QQ调用、坏证据隔离、只读查询权限与信息最小化 |
| G3d 独立综合 | 分项报告与综合记录 | 2–3个互不重叠单元串行，另一个Agent综合；额度不足明确未评审，不替代H1/G2/P6原关卡 |

每单元开工重读六文档、记录指纹/允许路径/验证，源码与测试按职责分子包，保持400行/10文件门槛。只跑新增和受接口影响节点，避免全套重复；外部服务用替身，SQLite/Redis仅独立临时实例。杀进程探针只终止本测试创建且核验身份的子进程，不能杀现有服务。

## 开发者需要决定的扩展

是否采用上述SQLite完成证据、调用前本地写失败暂停生成/返回后本地冻结失败暂停回复，以及本地持久目录/准入水位方案；若保留当前实现，L1继续明示未知金额不可补齐，不能称自动恢复完整。已有G1调用前Redis故障暂停与H1发送计划故障批准不等于本扩展已批准。

采用后先补齐当前被额度阻断的H1/G2/P6独立评审，G3实施也要独立验收；只读方案准备不授权提前跳过评审。回退停用新准入、完成或保留所有本地待办后撤回接线，不直接删除SQLite文件、永久生成证据或幂等回执。原进程不得与新进程同时生成同一旧尝试；回退不能重跑provider来清空积压。

本次仅新增上述提案并固化B2覆盖，未实施G3。结构扫描2026-10-06 11:36 +08:00为473文件/454文本、0大文件/0拥挤目录；差异检查通过。最后事实fallback接入约束只补充文档，未重跑已通过业务测试。SQLite原理引用以官方说明为依据，实际平台刷盘/容器卷/重启恢复尚未验证。
