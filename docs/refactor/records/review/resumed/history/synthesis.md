# H1a / H1b / H1c 与 C1 修复第三位独立综合评审

## 范围、开工与结论

- 2026-10-05 独立评审，未参与这些基础模块或 C1 实现；规定文档及两份分项证据已于 23:06:11 +08:00 前重读完毕。重读 AGENTS.md、六文档 project/development/plan/modules/status/audit、完整 B3.md、H1a/H1b/H1c.md、review/resumed/history/snapshot.md 与 session-plan.md；路径内未发现更具体 AGENTS.md，父工作区无该文件。
- 用户本单元唯一授权写入 `docs/refactor/records/review/resumed/history/synthesis.md`。六个实现文件和三份专属测试只读；隔离 probe 另读取既有 isolated_redis 函数及 valid_id 定义。没有读取或修改主 Agent 正在新建的 tasks/task_scripts、chat/history_delivery、其测试或 H1d 记录，没有加载 history_commit 包入口。
- 保留契约：原始来源/字节冻结；会话 CAS 与永久回执；旧补记冲突保留新会话；完整发送计划失败关闭；首次 create/begin 才能授权一次传输；unknown 不自动补记或重发；sent 同次 SET 激活两项历史任务；首次 ACK 观察时间冻结；生成费用独立保留。
- **结论：当前哈希下 H1a/H1b/H1c 基础模块可附限制通过。未发现新增 P1/P2；Hooke C1 对公开 sent 时间参数及既存记录解码的修复充分，可以在该范围关闭。另保留一项 P3/C2：Redis 产生的创建/开始时间没有写前范围检查，因此 H1c.md 的“超范围在任何写入前拒绝”表述过宽。**
- 这不验收 H1d 消费者、恢复/Owner、实际 transport/pipeline 接线、完整 H1、生产持久性或实群行为。下文接入建议不构成其他结构或业务改动授权；本评审未改实现或测试。
- HEAD 为 `8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9`；九文件均未被 Git 跟踪，结论绑定工作区 SHA256，不能以 HEAD 代替实现版本。

## 当前核对哈希

| 文件 | 物理行数 | SHA256 |
| --- | ---: | --- |
| src/services/persistence/history_commit/snapshot.py | 79 | 11da116fb9bd56ac45879e1c49bd7c8d1c12f41d5fed48c4c77ec51ffb01a5a3 |
| src/services/persistence/history_commit/session.py | 65 | e3b121e2cfafbc44b6a4eca4c3de5e19c31d5bfc0454e1a034637d6502b8ff83 |
| src/services/persistence/history_commit/session_scripts.py | 36 | 7c59362a7961415fc0ab9f1c39969051fc150aed05152c5ac96a29b554909a85 |
| src/services/persistence/history_commit/plans.py | 117 | e3387048a3c495ce70599c43be9d6122eecf56b41ee518ba7c8e34f721c455c1 |
| src/services/persistence/history_commit/delivery.py | 122 | 9266957d3eae1aa4fb17109f34cb0b3f7abd70c1012d284cb21db35ab30f0c25 |
| src/services/persistence/history_commit/delivery_scripts.py | 51 | 591756c4b59a6ed8a0db57ede3a86e154fca811da5ec96cad415f2422b6b329a |
| test/persistence/history_commit/test_snapshot.py | 47 | 2c7532ee69fdc345440ba9cbeaf32d9eb5b3c8f0b64379acd20da690be8babfa |
| test/persistence/history_commit/test_session.py | 110 | 306c8b9ac3154a7bca3fca1ffb237e52ce8e37d56ec7c9f8ed91f7f40a17f745 |
| test/persistence/history_commit/test_delivery.py | 145 | 6a1175bf1fde65d0288ca198e4444ba5b3bd1195f3e9e3f71da3db22ee943949 |

H1a 两文件、H1b 三文件（含测试）及 delivery_scripts.py 与两份分项报告相符。C1 后 plans.py 从 107 到 117 行、delivery.py 仍 122 行、test_delivery.py 从 131 到 145 行，三者哈希均已变化；Hooke 的旧哈希不代表修复后这三文件。Lua 没有随 C1 改动。

| 证据文件 | 行数 | 本轮 SHA256 |
| --- | ---: | --- |
| docs/refactor/records/review/resumed/history/snapshot.md | 60 | 74a7bfadf8e2746b6920364357b3898e0f371c76b699f5b87d9d4238561de43d |
| docs/refactor/records/review/resumed/history/session-plan.md | 77 | 78ab85baab3e594aafaa738a5840c0229f684996b3cd3b6a663d25782cb04e35 |
| docs/refactor/records/chat/history/H1c.md | 17 | 64beb49bcbd1a8d58d6b50c3ed4287a77bcec448d66dde453e164bfbc35d928f |

## 两份证据的可采用边界

| 来源 | 可采用的独立证据 | 不能扩张的结论 |
| --- | --- | --- |
| Chandrasekhar snapshot.md | H1a 79 行实现与 47 行专属测试；Python 3.13.5 / redis-py 6.2.0 的离线 RESP2/RESP3 字节与非法响应检查，报告记 1.58 秒；Lua 静态只有 TYPE/GET。当前两文件哈希吻合。 | 未执行 Redis Lua、隔离/生产 Redis、Hiredis 或 H1b；不能用该报告证明 CAS、送达或完整恢复。原 7 项仅为已记录实现验证，本轮未复跑。 |
| Hooke session-plan.md | H1b 会话/回执 CAS、H1c 完整计划和状态的静态检查；Python 3.10.20 / redis-py 6.4.0 / Redis 5.0.14.1 的 conflict 丢响应与回执 TTL probe（2.266 秒）；C1 时间反例 probe（1.797 秒）。未变文件哈希吻合。 | C1 probe 退出 0 表示成功记录两个反例，不表示时间均保真；原 8+6 项仅阅读。报告未验消费者或接线，也未覆盖修复后三文件；这里补核修复差异。 |
| 主 Agent H1c.md | 单项新增 test_ack_time_boundary_is_exact_and_oversize_never_mutates 记载 Python 3.10 / 隔离 Redis 1.82 秒通过；源码断言三种超限参数不改 DUMP，14 位上界能读回且幂等。 | 1.82 秒是实现方证据，未冒充本评审执行；本轮没有重跑该项、旧 7+8+6 项、全套或全仓结构扫描。该项没有覆盖三个时间字段的坏记录解码、sent 写后丢响应或精确 1MiB。 |

## 基础契约与 C1 修复复核

| 项目 | 当前依据与判断 |
| --- | --- |
| 快照来源与原文 | snapshot.py:11–19 一次 Lua 优先规范 key，坏规范值不退旧值；:36–56 区分 missing，冻结 bytes，视图独立；:68–79 使用 NEVER_DECODE 并将不可用/坏数据分别关闭。读取不做迁移写入。只校验 list[dict] 外形，未证明 role/content 业务语义。 |
| 会话替换与永久结果 | session.py:38–48 摘要绑定 session/source/原始 base64/完整裁剪后 JSON/保留参数。session_scripts.py:8–15 永久回执先于当前会话；:20–27 比较 current/legacy/missing；:30 保存终结 conflict，:34 单 MSET 写会话和 applied。迟到重试不覆盖较新会话，legacy 证据不删除。两个并发测试实际用 missing 来源，未将其描述为三种来源全部实测。 |
| 完整计划与稳定身份 | plans.py:39–77 严格 schema、目标、规范 UTF-8、1MiB、裁剪参数和原始快照；:96–99 派生独立 session/global effect_id。plan_json 在外层 Redis JSON 中是字符串，因此计划内 ID/历史数字不经 Lua 数值重编码；C1 收窄 timestamp_ms，没有顺带收窄所有业务整数。 |
| 一次授权与送达激活 | delivery.py:75–87 仅首次确认 create 返回 token；delivery_scripts.py:19–30 原字节 CAS、永久 TTL、prepared 首次 begin；:37–39、49 在同一次 SET 保存 sent/时间及两个 pending。unknown/rejected 不产生历史权限，未知发送可接受原 token 晚 ACK。基础模块自身不写 all_memory。 |
| C1 时间边界 | plans.py:14、28–32 限制严格 int 且 1 <= value <= 99999999999999，保持既定整数格式；delivery.py:106–107 在 GET/EVAL 前校验 sent 输入；:36–41 校验 created、相关状态的 begun 和 sent 的 delivered。bool、浮点、字符串、空值和越界既存时间都不能绕过读取校验。 |
| 确认幂等 | delivery_scripts.py:33–35 对 sent 同时间提前返回，异时间 denied；不再次激活或重置任务进度。本轮新增丢响应/合成任务进度 probe 验证此点。它不证明调用方确实传入首次 ACK 时间，也不证明消费者租约协议。 |

## 优先级、具体遗漏与建议

| 优先级 / 状态 | 发现、影响与明确建议 |
| --- | --- |
| P1：本基础范围新增缺陷 0 | 不据局部 API 报告批准生产接线。未来若由 inspect/扫描结果恢复传输权限，或 unknown 自动补记/重发，将违反当前契约；应作为接线验收阻断条件检查，而不是声称已发现未读 H1d 的缺陷。 |
| P2：本基础范围新增缺陷 0 | 后续接入前补同请求绑定、最终 guard、原子任务资格/租约、两目标独立结论及实际入口故障检查。当前无这些模块的实现证据；应保留未验收状态，不能由“基础通过”改写为“完整 H1 通过”。 |
| P3 / C1：本范围已关闭 | 对调用方 delivered_at_ms 的超限输入先拒绝、14 位上界精确保留；三个时间字段的解码也统一关闭坏记录。本轮补矩阵和真实 Lua 丢响应验证。已经由旧代码舍入的记录仍须保留待核对，不得把 float 转 int 或猜回原时间。 |
| P3 / C2：条件性边界仍开放 | delivery_scripts.py:6–10、26–30、49 将 Redis TIME 计算出的 now 直接写入；timestamp_ms 只在后续解码检查，create 返回 token 与首次 begin 返回 sending 前没有检查这个新时间。替换 TIME 来源为合成超限值 100000000000001 后，两条实际存储路径均写成功、cjson 舍入、随后 inspect 需核对。该反例需远超过当前 epoch 量级的服务端时间，不是当前正常时间路径的 P1/P2，也不重新否定公开 sent 参数的 C1 修复。建议实现方在原 H1c 范围考虑 CREATE/首次 BEGIN 的 SET 前范围检查并加专属回归；至少收窄 H1c.md:17“任何写入前”措辞，明确服务端时钟前提。本单元不实施该修改。 |
| P3：可重复证据遗漏 | 专属 test_delivery.py:134–145 仅持久化了 sent 边界回归；三个解码字段、已舍入旧记录、sent 写后丢响应、任务进度不重置和恰好 1MiB 尚无对应持久测试。本轮短 probe 补独立证据，建议后续在获准测试单元固化必要用例，不为此复跑旧测试集。 |

## 本轮新增短 probe

采用 `../.refactor-snapshots/validation-py310/Scripts/python.exe -I -B -`，脚本仅经 stdin 执行，不保存脚本或 pycache。四个当前实现模块 snapshot/plans/delivery_scripts/delivery 原样载入独立内存命名空间，绕开项目包入口；effects 异常类使用替身，valid_id 替身与单独阅读的实际 64 位小写十六进制定义一致。实际 HistorySnapshot/计划/状态/Python 解码及 Lua 路径参与执行；没有以此声称检验公共包导出、真实异常类身份、配置或生产接线。

仅 AST 提取 test/autonomy/test_pending_atomic.py:15–48 的 isolated_redis，去掉 pytest 装饰器，其余生命周期不变：随机回环端口、INFO server/process_id 与 Popen PID 相等后才写；save 关闭、appendonly=no、临时目录、Windows 隐藏窗口；finally 关闭客户端并终止/等待自己的进程，随后 tasklist 确认 PID 已消失。没有导入该测试文件的自主业务依赖、连接生产库或清库。

| 探针 | 实际结果与范围 |
| --- | --- |
| S1 C1 解码、sent 丢响应、容量 | Python 3.10.20 / redis-py 6.4.0 / Redis 5.0.14.1，127.0.0.1:1897，PID 39288；进程退出码 0，shell 2.09 秒，脚本内部 1.172 秒。created/begun/delivered 各注入 9 个值（上限+1、两个旧大整数、已舍入 float、bool、零、负数、None、字符串），27 次解码均拒绝；五个合法状态控制通过。隔离存储注入三个字段的越界整数/舍入 float，12 次 inspect/transition 保持 DUMP 不变。 |
| S1 sent 收尾边界 | 在上限-1 时间执行真实 sent SET 后包装客户端丢 ConnectionError；读取仍是 sent、原时间与两个 pending。仅在隔离数据中合成 session=complete/global=needs_review，再同时间重试字节不变，不同时间 denied。合成进度不是调用消费者，也不证明任务目标执行。 |
| S1 精确 UTF-8 容量 | 合成中文计划规范编码恰好 1048576 字节，+1 字节构造被拒；精确上限计划经 create/begin/sent Lua 往返 raw、digest、snapshot bytes 均不变，最终 envelope 为 1048958 字节。没有静默裁剪。chat:history:group_8/all_memory 始终未写；样例只检容量与保真，不检回复与历史内容业务对应。 |
| S2 C2 服务端时间注入 | 同版本隔离环境，127.0.0.1:7303，PID 62780；退出码 0，shell 1.68 秒，内部 0.719 秒。只对内存 Lua 将 `local tm = redis.call('TIME')` 替换成 `local tm = {'100000000000', '1000'}`，计算值为 100000000000001。CREATE 返回 token，首次 BEGIN 返回 sending，落盘时间均成 100000000000000.0，随后实际 inspect 抛 EffectNeedsReview 且不改 DUMP。该 probe 成功复现限制，没有调整系统时钟或声称真实 Redis 当前 TIME 越界。 |

## 今后接入必须保留的条件

1. **原证据与同请求绑定**：生成输入、HistorySnapshot、最终回复正文和 ChatReply.history 必须属于同一请求；计划要保存该原始快照，不在发送后/恢复时重新读取基线。schema/digest 证明冻结内容完整，不能证明调用方从正确请求取数；role/content、纠错/正文截断与原裁剪规则需实际入口验证。
2. **只凭首次确认发一次**：计划持久失败暂停本次回复并保留已发生费用；创建/开始响应丢失不调用传输或重新获得权限。inspect 是 GET/解码，可返回原 token，且不查 PTTL；可读 prepared/sent 不是发送或目标写入授权。最终候选 guard 必须处在实际传输边界，排队取消、缺 ACK、取消/后台线程迟到不能激活历史。
3. **时间与坏证据保守收尾**：冻结首次 ACK 观察毫秒值与计划内时区，所有持久化重试使用同一值，不用当前 TIME/datetime.now() 补造。当前模块不保证 delivered >= begun 或跨时钟先后，合成测试不能证明真实 ACK 来源。时间丢失、旧舍入值、人工未知时间保留待核对，不能猜值或自动重发。
4. **历史效果独立**：未来消费者要原子校验 sent、完整绑定、永久 TTL、任务状态及自身租约；session/global 各用稳定 effect_id 和原保留参数。会话 HistoryConflict 保留新会话并终结旧目标，全局目标可独立执行；全局追加继续依既有 started/永久回执防部分写后重放。认领/取消/线程迟到、目标写后丢响应和结果 CAS 必须另审，本轮未读其实现。
5. **恢复与展示的边界**：恢复仅消费同一冻结计划，不持有模型/transport 发送能力；查询/Owner 不泄露正文、原始证据或 token，不把无时间/坏计划显示为已补齐。SCAN 只是发现，需有界预算、空非末页/重复/超量处理，读取失败不能假报空库。该基础报告没有这些功能的验收证据。
6. **原子比较与部署条件**：字节 CAS 只保证提交时基线匹配，不能识别首次比较前恢复原字节的 ABA 或 missing→创建→删除；永久回执也依赖证据不被驱逐/删除及 Redis 持久配置。单次 MSET/SET 的正常原子路径不证明崩溃/复制/资源耗尽下持久性。接线必须统一替换旧直接 commit 与重放路径，避免新旧写入者并存；回退保留原计划、状态、历史和回执。

## 验证限制与唯一改动

本轮仅执行上述两次新增短 probe；未运行旧 7+8+6 项、C1 单项或全套、Python 3.13 的新修复 probe、Hiredis、Redis Cluster、真实网络丢包、资源耗尽、Redis 崩溃/复制或生产持久化试验。S1 的故障为客户端包装，S2 是内存 Lua 时间来源替换；随机端口/PID 隔离不等于生产联调。两份旧分项的版本与范围不相互替代。

唯一持久改动：`docs/refactor/records/review/resumed/history/synthesis.md`。代码、测试、其他文档未写；没有读取 .env/秘密/真实聊天数据，没有启动应用/模型/QQ，没有提交、推送或部署。临时目录和隔离 Redis 进程均已清理。回退只移除此报告，不能删 Redis 证据或回滚其他 Agent 的并发工作。

交付复核：2026-10-05 23:10:36 +08:00，九个实现/测试和三个证据文件 SHA256 全部与上表一致。本句追加后报告 91 行、0 行尾空白，history 审查目录 3 个直属文件；仅做局部结构检查，没有全仓扫描。后续并发修订不在本哈希结论内。

## C2 修复后独立静态追加核对（2026-10-05）

- 追加读取/哈希复核完成于 23:20:19 +08:00。重新读 AGENTS、六文档及 B3 的 H1 约束、H1a/H1b/H1c 记录；本次仅核对 C2 的两文件差异，唯一写入仍为本 synthesis.md。未读 tasks/task_scripts、chat/history_delivery 或其他 H1d 新代码及测试。
- **P3/C2 修复已获独立静态确认，基础范围继续附限制通过，无本次差异引出的新增 P1/P2。** 上文 C2 反例、“仍开放”状态及旧哈希保留为原审查时的历史结论；本追加仅适用于下列修复后哈希，不把原 probe 当作新 Lua 的执行证据，也不扩大到 H1d 或生产接线。

| C2 追加核对文件 | 原行数 / SHA256 | 修复后行数 / SHA256 |
| --- | --- | --- |
| src/services/persistence/history_commit/delivery_scripts.py | 51 / 591756c4b59a6ed8a0db57ede3a86e154fca811da5ec96cad415f2422b6b329a | 57 / f097c2e96582f8bac6fc7e7ca01a6a5848d2dcd3f9b7393034aee7d3b5ed7b2e |
| test/persistence/history_commit/test_delivery.py | 145 / 6a1175bf1fde65d0288ca198e4444ba5b3bd1195f3e9e3f71da3db22ee943949 | 163 / 2c6857873b1456dade4d94e6d5fd379d7d48f5e5e54212c88e7d4a9986db9092 |

- 差异核对方式：从当前文本移除两段新增范围检查、移除新增测试（保留原测试文件无末尾换行的字节形态），复原 SHA256 分别精确匹配上表旧哈希；因此差异确为 Lua 两段各三行和一个新增测试，原断言未删改。另七个原实现/测试、两份独立分项报告哈希均与原表一致。追加前本报告 91 行，SHA256 为 a8a9a0baa85f569b17608e84192d7af4f021bc7347b34bfb5a77b7c9bdb2e648；原报告正文和原哈希范围保留。
- CREATE 当前 delivery_scripts.py:8–10 在构造记录及 :13 的 SET 前检查 now < 1 或 now > 99999999999999，并返回 error_reply；该路径此前仅 TYPE/TIME，非法服务器时间不能先落盘或返回 created。首次 begin 在 :32 确认 prepared 后，:33–35 同样先校验，再于 :36 设置 sending/begun，最终 :55 SET；非法 now 不改原 prepared 记录。上限与 plans.py 原已核对的 MAX_TIMESTAMP_MS 相同；sent/unknown/reject、token、原字节 CAS、TTL 与两项任务激活规则没有在本差异中改动。
- 新测试 test_delivery.py:148–163 经 eval 包装把内存 Lua 的 TIME 替换为 {100000000000, 1000}，计算值为 100000000000001，对应原 C2 超限反例；分别断言 create 抛 EffectNeedsReview 且 key 不存在、正常 create 后极端 begin 抛 EffectNeedsReview 且 DUMP 不变。替换仅作用于送给隔离 Redis 的脚本文本，不改系统时钟。新增测试没有断言零/负服务器时间或恰好服务器时间上界；两侧静态条件已核对，本追加不冒称这些情形已独立实测。
- 执行证据按用户本轮提供状态记录：主 Agent 已运行并通过该 C2 新项；其 24 项检查目前为 23 通过、1 项旧测试替身未返回显式 True，正在修正，用户说明该失败与 C2 无关。本评审未核查那项范围外失败或其修正，不推断 24 项全部通过，不将实现方执行结果冒充独立运行。
- 本次只做文本 diff、哈希及两文件 Python AST 静态语法解析，没有导入业务模块、运行 Lua、启动 Redis、重跑 C2/旧测试、创建新 probe 或运行全套/全仓扫描；没有应用、模型、QQ、秘密读取或代码写入。原验证限制、接入条件与 H1d 另行独立评审要求继续保留。唯一改动为此报告的追加，回退仅撤去本节。
