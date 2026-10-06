# G2a 费用待办索引存储实施记录

2026-09-30 开工：重读 AGENTS.md、project.md、development.md、plan.md、modules.md、status.md 及 B3 顶部 G2a–G2d；无更具体 AGENTS。
批准依据为开发者本次明确指令及 B3 的 G2 批准。串行仅实施 G2a，消费者与独立综合评审另安排。
允许写集：src/services/persistence/generation/、test/chat/generation/ 新增定向测试、本文。
保留原字节 CAS、模型 token 与费用 token 隔离、永久 generation/receipt、冻结金额和归属日；不改 config、消费者、插件、status 或 G1 报告。
验证范围限索引竞争、部分失败、重建和旧调用隔离；复用 PID 核对的临时隔离 Redis fixture，不读取 .env、不连接生产或真实模型。

## 中断后接手（2026-09-30）

Mencius明确返回workspace out of credits，留下索引/transition草稿但没有最终验证报告；不能视为实现验收。主Agent核对现有文件并补充test/chat/generation/test_index.py，四项隔离Redis检查通过（Python3.10，4.54秒）：pending/lease/retry/terminal索引同步、索引错类型仍保留模型completed证据及重建、旧原文/旧token不能改新租约、损坏和缺失成员移除索引但保留权威原文。
该四项不覆盖全部G2a：decode_responses=True客户端遇非法UTF-8成员可能使整批读取失败；错误类型或意外TTL的generation成员清理仍需核对。消费者与周期恢复尚未切换，独立复审没有完成。下一步先收口坏队头边界，再接G2b/G2c，不直接裸ZREM有效ID绕过原文比较。

非法UTF-8续修：核对本地redis/client.py的NEVER_DECODE命令选项，due_ids通过原始响应读取后逐成员解码；合法ID保持str，非法UTF-8保留bytes交repair，不丢弃整页也不改变客户端全局解码设置。新增隔离Redis探针在默认decode_responses=True客户端混入b'\xff'和正常pending，确认两项均可读、仅清除非法成员、正常费用仍pending；1项通过（Python3.10，1.99秒）。错误类型/意外TTL边界及G2b/G2c仍未完成，不将此项视作G2验收。

意外TTL续修：repair在原文CAS匹配后检查当前PTTL；带过期时间的记录只移除费用发现索引并返回removed_invalid，不修改generation正文或TTL，不授权计费。人工修复永久性后可用新快照重建。新增隔离Redis检查1项通过（Python3.10，1.59秒），确认正文保留、TTL没有延长及修复后重建；代码不会自动执行测试中的PERSIST。错误Redis类型的队头、消费者/修复扫描接线和独立复审仍待完成。

错误类型续修：新增repair_current，以原始字节读取TYPE及字符串快照；字符串按原文CAS走repair，非字符串只在原子复核仍为所观察的非法类型时ZREM发现项，不改源记录。迟到隔离遇正常字符串替换返回changed，不能移除新任务。两项新增隔离Redis检查通过（Python3.10，3.93秒），包括hash源DUMP保持、正常替换保护及非法UTF-8正文保留。G2b可调用due_ids(limit=3)后repair_current(member)并对合法ID走费用claim；索引不是授权，仍需完成消费接线和独立评审。
