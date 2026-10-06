# H1a 会话快照独立核对

## 开工与授权

- 本次为 2026-10-05 新的独立 H1a 工作单元，不是旧 G2 任务重派；未参与 H1a 实现，不评审主 Agent 正在实现的 H1b。
- 规定文档重读完成时间：2026-10-05 22:35:46 +08:00。已重读 AGENTS.md、docs/agent/project.md、development.md、docs/refactor/plan.md、modules.md、status.md；另重读 records/chat/B3.md 的 H1 批准与实施约束、records/chat/history/H1a.md。仓库内未发现更具体的 AGENTS.md，父工作区没有 AGENTS.md。
- 批准依据：用户本轮明确授权独立只读核对；B3.md:239–263 记录 H1 已批准，旧会话补记冲突保留新会话，发送前计划保存失败暂停该回复。
- 唯一允许写入路径：本记录。业务代码只读 src/services/persistence/history_commit/snapshot.py、test/persistence/history_commit/test_snapshot.py；不读取 H1b 未完成代码，不修改实现或测试。
- HEAD：8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9；两个核对文件均为未跟踪工作区文件，结论须绑定文件哈希，不能以 HEAD 代表新实现。
- 保留契约：现代 key 优先；缺失与坏数据/不可用分开；原始字节独立于消息视图；读取不迁移、不写入、不降级到内存；未来提交必须使用同一请求冻结的快照。
- 验证范围：逐行静态核对与具体风险的离线小探针；不重复既有 7 项 pytest，不启动应用、不接真实 Redis/QQ/模型、不读取秘密。

## 核对基线

| 文件 | 物理行数 | SHA256 |
| --- | ---: | --- |
| src/services/persistence/history_commit/snapshot.py | 79 | 11da116fb9bd56ac45879e1c49bd7c8d1c12f41d5fed48c4c77ec51ffb01a5a3 |
| test/persistence/history_commit/test_snapshot.py | 47 | 2c7532ee69fdc345440ba9cbeaf32d9eb5b3c8f0b64379acd20da690be8babfa |

## 结论与发现

在上述两个文件及哈希范围内，未发现新的 P1/P2 缺陷；H1a 快照读取边界可附下述限制通过独立核对。该结论不验收 H1b CAS、发送计划、恢复消费者或完整 H1，也不将旧 G2 任务或其他历史报告算作本轮证据。

| 关注项 | 当前证据与判断 |
| --- | --- |
| 原始字节 | snapshot.py:68–75 使用 NEVER_DECODE=True，未做 JSON 重序列化；:36–52 要求非缺失 raw 为 bytes，frozen dataclass 保存证据；:54–56 每次独立解析消息视图。新增实际客户端/离线解析器探针确认自动解码开启仍保留 UTF-8 字节、空白与转义。 |
| 现代/旧 key/缺失选择 | :11–19 一次 Lua 按 chat:history:<session>、<session> 顺序选择；现代 key 类型异常立即报错，现代 key 存在时不读取旧 key。空字符串也作为已存在现代值返回，随后解析失败，不按空会话或旧值继续。仅两者都缺失返回 source=missing、raw=None。 |
| 响应与故障关闭 | :70–75 校验列表、严格整数来源、合法来源编号及长度；构造快照继续验证字节/UTF-8/JSON/list[dict]。:76–79 将连接/超时区分为 EffectUnavailable，其余错误为 EffectNeedsReview；不会返回空列表或取内存后备。非法 session_id 在 :64 直接抛 ValueError，也不会伪造缺失。 |
| 读取不写入 | Lua 只调用 TYPE、GET；Python 路径只有 EVAL、校验和对象构造，没有迁移、SET、DEL、TTL 修改或其他目标提交。读取失败后也没有恢复写入。不能据此宣称服务端过期、驱逐或持久化机制静止。 |
| 测试证据范围 | test_snapshot.py:11–27 覆盖来源、原始空白/嵌套字段、独立视图和 DUMP；:30–38 五类坏现代正文不回退；:41–47 旧 key 错类型及不可用。共 7 个 pytest 场景仅阅读，未重复执行；H1a.md 中旧运行结果只是实现记录，不冒充本轮执行。 |

## 新增离线小探针

本轮使用 ../mako-bot/.venv/Scripts/python.exe -I -B -：Python 3.13.5、redis-py 6.2.0，退出码 0，1.58 秒。代码从 snapshot.py 读取并执行，只替换相对 effects 导入的两个异常类；不导入项目包入口或测试 fixture，不产生 pycache、临时探针文件或真实连接。

1. 自动解码与协议边界：使用实际 redis.Redis.execute_command、ConnectionPool 和 Python RESP2/RESP3 解析器，连接替身只消费内存中的 RESP 响应，禁止建立 socket。decode_responses=True 下，带 UTF-8 非 ASCII 内容、JSON 转义及尾部空白的数组内 raw 与输入逐字节一致，类型为 bytes；NEVER_DECODE 没有被发送为 Redis 命令参数。两种协议均通过。
2. 非既有返回结构：依次注入 [True,b'[]']、[3,b'[]']、[0,b'[]']、[1]、(1,b'[]')、[1,'[]']、[0,None,None]，均抛 EffectNeedsReview。这是一个新增响应校验探针的七种输入，不是重跑既有 7 项 pytest。

另静态提取 Lua 的 redis.call 命令，结果仅 TYPE、GET。未运行 Lua；客户端探针只证明已安装解析器/调用选项的字节处理与 Python 关闭路径，不冒充真实 Redis 原子性或网络故障试验。Hiredis 未安装，未声称覆盖。

## 后续 CAS 接入必须保留的条件

以下是 H1a 证据的使用约束，不是对未完成 H1b 的缺陷判断；本轮没有读取它的代码。

| 冻结来源 | 提交时的必要基线判断 |
| --- | --- |
| current | 规范 key 的当前原始字节必须与 snapshot.raw 精确一致；不可比较 messages() 的语义或重序列化结果。旧 key 不应替代已选中的现代来源。 |
| legacy | 同一原子提交中确认规范 key 仍缺失、旧 key 原始字节仍等于 snapshot.raw；成功只写规范 key，保留旧证据。并发出现现代值时冲突，不能迁移覆盖。 |
| missing | 同一原子提交中确认规范 key 和旧 key 都仍缺失；不能只检查规范 key，不能把 [] 当作缺失或把读取异常转成 missing。 |

快照的 session_id/source/raw 必须与生成及回复属于同一请求，发送后或恢复时不得重新读取来替换基线；计划持久化须采用可精确还原 bytes 的编码，不能只保存清洗后的 messages()、JSON 摘要或重新生成的 JSON。成功目标写入和永久 effect 回执、会话冲突与独立全局效果仍待后续单元验收。

## 限制与交付边界

- 未运行既有 pytest、真实 Redis 或隔离 Redis 服务；Lua 来源选择/原子性本轮只有静态证据。旧记录中的 7 项通过证据不重复也不扩张。
- 新探针仅覆盖 Python 3.13.5 与已安装 redis-py 的 Python RESP2/RESP3 解析器；未执行 Python 3.10、Hiredis、Redis Cluster、TTL/驱逐或真实断连场景。
- 快照只保存来源和原始字节，不是版本号或租约：字节完全恢复到原值的 ABA，或缺失后创建再删除的变化，不能单靠本快照识别。未来字节 CAS 保证的是提交时基线相等，不能承诺检测所有曾发生的变更。
- decode_history 仅验证外层 list[dict]；role/content 语义、提示词规范化与既有调用方兼容性未在这两个文件内证明。快照读取没有容量上限；完整计划序列化容量仍须按 B3 的真实边界验收，不能静默截断原始证据。
- 未读取/评审 H1b 或其他业务代码，未接生产聊天链路；没有 QQ、模型、真实数据、秘密、提交、推送或部署操作。
- 唯一写入为本报告。2026-10-05 22:42:33 +08:00 交付复核：两个核对文件 SHA256 与表内基线一致，物理行数仍为 79/47；报告 60 行、无行尾空白，review/resumed/history 仅 1 个直属文件。未运行全仓结构扫描。回退仅移除本次报告；没有业务改动或 Redis 数据需要回退。后续并发修改不属于本结论。
