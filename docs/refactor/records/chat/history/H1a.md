# H1a 持久会话快照

2026-10-05，重读AGENTS、project、development、plan、modules、status及现有history/engine/pipeline。依据开发者明确批准H1，允许新增persistence/history_commit快照与后续CAS目标、专属test/persistence/history_commit及本记录；暂不切换生产调用。

当前读取将坏JSON或异常转空历史，旧key读取还会无条件迁移覆盖。新快照通过一次Redis脚本选择规范key或旧session key，保留原始字节与来源；缺失单独表示，坏数据或不可用不降级。规范key存在时优先，即使其正文为空/损坏也不回退旧值。

迁移安排在后续H1b基线CAS提交时执行，而非读取时写入：旧基线要求规范key仍缺失且旧key字节未变，随后只写规范key，旧证据保留。这样读取为纯操作，不以读取失败/并发迁移覆盖新会话。后续计划保存原始快照，不用提示词清洗后的列表重建证据。

不改变现有HistoryRepository接口、裁剪规则、提示词或发送行为；完整H1须计划与恢复齐备后接线。独立Agent额度失败已确认，未重复派发，待补分项及综合评审。验证范围：规范/旧/缺失来源、原始字节、坏类型/JSON/编码、故障关闭和读取不写入。

上轮Python3.10隔离Redis及断连替身7项通过（9.61秒），工具完成结果已返回；随后文档补写/结构扫描调用被用户打断，本轮仅恢复记录，不重复已通过测试。原始空白及嵌套字段保留、修改视图不改证据、现代空列表优先、DUMP前后一致、五类坏正文和故障关闭均有断言。

2026-10-05启动新的独立快照分项Chandrasekhar（01a10c7b-73bf-7a11-950b-69b6c86bf6a1），报告目标review/resumed/history/snapshot.md；启动不等于通过。CAS与发送接线仍待其对应验收。

Chandrasekhar已明确completed并交付独立报告：限定快照两文件哈希未发现新增P1/P2，可附限制通过；未重复7项测试，新增Python3.13客户端/RESP解析离线探针通过。限制含未验真实Redis/Hiredis、只验证list[dict]外形及字节CAS的ABA边界，不覆盖H1b或完整H1。完整报告见review/resumed/history/snapshot.md。
