# H1b 会话历史基线提交

2026-10-05，重读AGENTS、project、development、plan、modules、status和H1批准；恢复上轮中断时确认快照代码已保存，H1a验证记录补写仍未执行。允许路径history_commit/session.py、session_scripts.py、专属测试及本交接；不切换聊天生产入口。

SessionHistoryWriter.apply绑定effect_id、session、原始来源/字节、裁剪后新正文与冻结max_history_turns。规范历史匹配原字节才替换；旧来源要求规范key仍不存在且旧字节匹配；缺失来源要求两key仍不存在。旧证据不删除，裁剪沿用最近max_history_turns*2条。

匹配时单MSET保存会话和永久applied回执，无先行目标修改；回复丢失重试先查回执，不覆盖较新历史。基线冲突仅保存永久conflict回执，不改会话；即使旧字节后来被外部恢复，同effect也不能复活。相同ID不同冻结载荷报身份冲突，与新会话冲突区别。坏回执/TTL或Redis故障不降级。

验证计划限隔离Redis并发两旧基线、现代/旧迁移/缺失竞态、成功后新会话与迟到重试、写后响应丢失、裁剪及坏回执。全局记录仍由独立EffectWriter任务处理，发送计划与恢复尚未接线；本目标API不能单独作为送达授权。独立H1a Agent已启动，H1b另待后续分项与综合评审。

实际Python3.10新增8项通过（12.54秒），含两个并发旧基线仅一成功、冲突后外部恢复旧值仍拒绝、三类迁移竞态、冻结裁剪和legacy原文保留、MSET写后丢响应及后续新历史不被重试覆盖。未重复H1a及全套测试。原始字节CAS无法识别发生在首次比较前且已恢复同字节的ABA写入，未引入未批准的全仓版本迁移；现有永久冲突回执只保证已拒绝操作不能复活。
