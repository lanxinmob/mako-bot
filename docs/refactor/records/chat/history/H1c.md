# H1c 发送前冻结历史计划与送达状态

2026-10-05，依据已批准H1，继续同一持久历史模块；重读Agent说明和原发送/补记目标接入契约。范围history_commit/plans.py、delivery.py、delivery_scripts.py及专属测试；暂不切换生产入口。用户批准的发送前计划保存失败暂停、unknown不自动补记/重发、会话冲突保留新历史契约保持。

计划完整绑定action_id、bot、目标用户/群、原始会话来源字节、回复正文、裁剪后历史、两项保留参数与时区偏移。采用独立chat命名空间，避免后台DeliverySpec的正文长度边界造成截断；完整UTF-8序列化最多1MiB，超量拒绝保存并暂停该回复，不静默裁剪正文或原证据。历史只沿原max_history_turns*2规则裁剪，计划不改费用。

只有首次create确认返回新token；已有ID或写后响应丢失不重新授权。begin要求原token和prepared快照，真实传输回调未来必须在该确认后才调用QQ。sent使用单次SET同时保存确认时间及session/global两任务pending；unknown/未发送任务全部dormant。迟到同tokenACK允许unknown转sent；重复sent不会换时间。reject仅prepared可变更，未确认不产生历史补记权限。未给聊天发送新增自动超时分类，也未将生成的5分钟策略套用于发送。

sent接口要求调用方传首次观察ACK时冻结的delivered_at_ms，不用后续持久化尝试的Redis时间；相同时间幂等、不同时间拒绝。该字段是传输确认观察时间，不能冒称QQ服务端精确送达时刻；时间丢失时须保持待核对。主Agent复核后修改了该尚未接线API，通知第二位评审Agent基于当前文件复核，受影响两项定向通过（4.89秒）。

该阶段仅保存发送/补记计划与状态，不执行历史目标、模型或QQ。后续独立任务租约、恢复、Owner核对及实际transport/pipeline必须一起接线；不能将基础API当成已解决生产双写。回退保留新记录及原history/receipt，无自动数据删除。独立快照分项已完成，后续分项与综合评审待完成。

Python3.10新增6项通过（7.61秒）：create与begin写后丢响应不再授权、原token未知后晚ACK与时间幂等、未发送/缺失/拒绝不激活任务、Unicode正文远超原后台Spec容量仍完整保存及超1MiB明确拒绝、目标错配/坏digest/TTL故障关闭。H1a独立分项随后已completed，H1b/H1c另派独立Agent，完整H1仍未验收。

第二位独立Agent Hooke（01a10c86-040b-7971-a7cf-ac774fd35a3b）已completed，报告review/resumed/history/session-plan.md。H1b无新增P1/P2，H1c指出C1/P3：Lua cjson将API接受的15位及更大确认时间舍入，随后无法读取。当前正常epoch量级不受该反例影响；基础范围之外的消费者和接线仍未验收。

主Agent修复C1：维持整数持久格式，增加MAX_TIMESTAMP_MS=99999999999999，创建/开始/确认时间解码及sent参数采用同一精确容量校验。超范围在任何写入前拒绝，不默改时间。新增单项隔离Redis检查通过（Python3.10，1.82秒）：14位上界精确保留并幂等，三种超范围值不改变原sending记录。没有重复原8+6项；第三位独立Agent将综合两份分项与当前修复。H1d将继续独立开发，不能据基础报告宣称整个H1通过。

McClintock（01a10c92-cfc0-7171-99ca-bd382e989ebf）已completed第三位基础综合报告synthesis.md；C1关闭，另C2指出Redis TIME创建/开始值也须写前范围校验。主Agent在CREATE/首次BEGIN的SET前检查同一上限，新增隔离TIME注入检查通过。综合Agent完成C2差异/哈希独立追加静态核对，基础附限制通过；旧大整数记录保留待核对，不猜回原值。该报告不覆盖新增H1d或真实发送。
