# H1b / H1c 基础模块串行独立核对

## 开工、范围与基线

- 2026-10-05 独立只读审查，未参与本模块实现。先完成 H1b（22:48 前），再进入 H1c（22:49:04 +08:00 读取当前修订版）；交付前文件复核时间为 22:51:54 +08:00。
- 开工重新读取 AGENTS.md、六文档 project/development/plan/modules/status/audit，以及 B3.md:239–263 的已批准 H1、chat/history/H1b.md、H1c.md 和 Chandrasekhar 的 review/resumed/history/snapshot.md。进入 H1c 前再次读取约束文档和当前 H1c 记录；项目和状态文档在此期间有主 Agent 更新，以当前批准与用户消息为准。未发现路径内更具体的 AGENTS.md，父工作区没有该文件。
- 用户本轮只授权核对下表五个实现文件和两份专属测试；唯一持久写入路径为本报告。为隔离探针读取既有 test/autonomy/test_pending_atomic.py:15–48 的 fixture 定义。没有读取新的效果消费者或其他未完成实现。
- 保留契约：冻结原始来源/字节；会话 CAS 与永久回执；冲突保留新会话；完整计划保存失败关闭；create/begin 不重授权；unknown 不激活；sent 同一次 SET 激活两项历史任务；确认时间来自首次 ACK 观察并冻结。
- HEAD 为 8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9；七个被核对文件均为未跟踪工作区文件，以下哈希才是本结论的实现基线。初读与交付前复核一致，后续变化需另核对。

| 文件 | 物理行数 | SHA256 |
| --- | ---: | --- |
| src/services/persistence/history_commit/session.py | 65 | e3b121e2cfafbc44b6a4eca4c3de5e19c31d5bfc0454e1a034637d6502b8ff83 |
| src/services/persistence/history_commit/session_scripts.py | 36 | 7c59362a7961415fc0ab9f1c39969051fc150aed05152c5ac96a29b554909a85 |
| src/services/persistence/history_commit/plans.py | 107 | a9a804fe995f9c0aec821eec56d2b39f4edf66616b56dc82d8b228bdd2672a59 |
| src/services/persistence/history_commit/delivery.py | 122 | 320d9677a2337dd3a9c591ff55a0d15643736190a3baeaef1ed7cfc5df966c1c |
| src/services/persistence/history_commit/delivery_scripts.py | 51 | 591756c4b59a6ed8a0db57ede3a86e154fca811da5ec96cad415f2422b6b329a |
| test/persistence/history_commit/test_session.py | 110 | 306c8b9ac3154a7bca3fca1ffb237e52ce8e37d56ec7c9f8ed91f7f40a17f745 |
| test/persistence/history_commit/test_delivery.py | 131 | edf441cbb2c85b3c6e54840d8907c6f57fe3d80d8e192e27470218b6a2e43187 |

## 结论与具体问题

在上述哈希范围内，H1b 未发现新增 P1/P2；H1c 未发现新增 P1/P2，存在下述 P3 时间范围边界问题。两项基础模块可附该问题和接入限制通过本次分项核对；不验收整个 H1、租约消费者、恢复/Owner 或生产发送。主 Agent 更新后的 sent 时间 API 是本次实际审查对象，没有沿用旧版 Redis TIME 充当确认时间的实现。

**C1 [P3] 接受的时间整数范围超过 Lua JSON 的实际精确保真范围。**

- 定位：plans.py:19–22 允许全部正整数小于 2**53；delivery.py:106–107 将此规则用于 delivered_at_ms。delivery_scripts.py:32、38、49 将参数转为 Lua 数值并通过 cjson.encode 保存；随后 delivery.py:40–41 要求读出的时间仍是 Python int。
- 新隔离探针通过实际 create/begin/sent API 传入 100000000000001：sent 返回成功，存储的 JSON 被解析为 100000000000000.0，inspect 抛 EffectNeedsReview。传入 9007199254740991 时存成 9007199254741000.0，同样无法 inspect。已经持久化的 sent 记录与已激活任务因此成为不可读的待核对证据，原时间也已丢失。
- 当前日期量级的 1791240000123，以及 14 位控制值 99999999999999，均精确保留。问题只在远大于当前 epoch 毫秒的已接受输入边界，因此列 P3，不将其说成当前正常 ACK 时间路径的 P1/P2。
- 建议在尚未接线阶段收窄并明确支持的时间范围，或采用可保真编码后严格还原整数；避免 API 先接受、写成功后才因数值序列化失真而拒读。应由实现方选择兼容方案，本轮未改代码。

## H1b 核对证据

| 关注项 | 当前代码与测试证据 |
| --- | --- |
| 两个旧基线竞争 | session_scripts.py:18–27 与 :34 在同一 Lua 内比较并 MSET，会话写入和 applied 回执属于同一命令；不同冻结结果的两个当前/旧/缺失基线请求不能都覆盖同一旧状态。test_session.py:33–56 的竞争用例实际采用 missing 基线，不将其描述为三种来源都已实测。相同结果/字节未改变的情况不等同于新会话被覆盖。 |
| 来源条件 | :20–21 要求 current 的规范 key 为 string 且字节精确一致；:22–25 要求 legacy 的规范 key 仍不存在、旧 key 的类型/字节匹配；:26 要求 missing 的两 key 都不存在。成功不删除旧证据。test_session.py:59–82 阅读确认覆盖并发新规范值、旧值改变、缺失后新旧 key 及 legacy 裁剪。 |
| 冻结载荷绑定 | session.py:38–48 将 session/source/raw base64/裁剪后完整新 JSON/max_history_turns 全部纳入摘要。相同 ID 改冻结参数或目标不能复用旧 applied/conflict 结论；只丢弃按原规则裁剪掉的消息，不截短保留消息内容。 |
| 永久回执优先 | session_scripts.py:8–15 先检查回执及 PTTL，再比较会话；applied 迟到重试不覆盖之后的新会话，conflict 已终结时不会因旧字节恢复而复活。test_session.py:18–30、85–97 是既有证据，仅阅读。 |
| 故障关闭 | session.py:49–64 区分 Redis 不可用、需要核对、历史冲突和身份冲突，不降级内存。坏回执类型/意外 TTL 不写目标；任意不匹配的永久字符串回执返回 identity_conflict，也不会重写目标。本轮新增冲突丢响应和回执 TTL 探针见下文。 |

## H1c 当前修订版核对证据

| 关注项 | 当前代码与测试证据 |
| --- | --- |
| 完整计划字节 | plans.py:14–16、29–31、54–67、99–106 保存完整 canonical UTF-8，原证据用 base64，正文不受后台 DeliverySpec 长度规则截断。上限按真正编码字节计 1048576；新历史只沿 max_history_turns*2 裁剪。超量/非有限数值/非规范 JSON 拒绝构造，持久化前即停止。test_delivery.py:94–112 仅阅读，既有 Unicode 用例不是恰好 1MiB 的边界测试。 |
| 身份、目标与效果 | plans.py:33–62 严格 schema，并核对 session 与 user/group；完整正文、历史、保留参数和时区包含在 digest 中。:86–89 为 session/global 派生不同稳定 effect_id。delivery.py:30–32 将计划摘要、动作 ID、token 绑定；create 遇已有 ID 只返回 None，不用新计划替换旧记录。 |
| create/begin 单次授权 | delivery.py:75–87 和 delivery_scripts.py:4–11 只有首次确认 create 返回 token；任何已存在记录无新 token。transition 先解码当前快照，再以 raw CAS；:28–30 只有 prepared 可首次 begin，已 sending/unknown/sent/rejected 均不能再次 begin。创建/开始写后丢响应的既有两项仅阅读，未重跑。 |
| unknown 与未发送 | delivery.py:37–49 要求 sending/unknown 的 begun 时间有效、delivered 为空且两个任务 dormant。delivery_scripts.py:40–47 仅允许 sending→unknown、prepared→rejected。无 ACK、prepared、rejected 或 missing 不激活历史，也没有自动重发分支。 |
| sent 原子激活 | delivery_scripts.py:37–39、49 在同一次 SET 保存 sent、调用方传入的时间和 session/global pending。新计划不被重新生成，两个效果仍有独立身份，后续会话冲突不得阻断全局效果。基础模块本身未写会话或 all_memory。 |
| 当前时间 API | delivery.py:101–109 要求 sent 显式传 delivered_at_ms，bool/None/零/非整数均拒绝；其他操作禁止携带该参数。delivery_scripts.py:32–38 保存该参数，不以 :26–27 的 Redis now 替代 ACK 观察时间。:33–35 对已 sent 只允许同时间幂等返回，不同时间 denied；提前返回也保留后续可能已变化的任务状态。test_delivery.py:23–49、82–91 为主 Agent 已同步修订的测试，本轮未执行。 |
| 坏记录与 TTL | delivery.py:24–50 校验容量、计划/摘要/token、状态/时间、两个任务及其激活关系；:63–73 将错误关闭为需核对/不可用。delivery_scripts.py:15–23 检查 key 类型、原始 CAS 和永久 TTL，遇异常不 SET。inspect 不检查 TTL，详见接入限制，不能把它当执行授权。 |

## 本轮新增受控探针

两次探针均使用 ../.refactor-snapshots/validation-py310/Scripts/python.exe -I -B -，通过标准输入执行，无持久探针脚本或 pycache。只从上述已审文件加载函数/Lua，替换相对导入为内存中的异常类、ID 校验和最小快照接口，避免项目包入口/配置初始化；不以这些替身声称验证了 H1a 构造校验或实际集成调用。

Redis 生命周期直接执行既有 isolated_redis fixture 的 AST 函数定义，仅去掉 pytest 装饰器；原有随机本地端口、INFO server/process_id 与子进程 PID 比较、启动/退出清理逻辑均保留。临时目录位于系统临时区，Redis save 关闭、appendonly=no、Windows 隐藏窗口；写入前验证 PID，只对本次进程操作，退出后关闭客户端并终止该进程。没有连接生产端口或清空其他 Redis。

| 探针 | 环境与实际结果 |
| --- | --- |
| B1 冲突回执丢响应 | Python 3.10.20 / redis-py 6.4.0 / Redis 5.0.14.1；本次 PID 53128，127.0.0.1:2763。目标已改变时 Lua 保存 conflict 后注入客户端 ConnectionError；恢复旧字节后同 ID/载荷仍 HistoryConflict，改冻结 max_history_turns 则 EffectConflict；回执 PTTL=-1，目标/回执字节保持。通过。与既有成功写后丢响应测试不同。 |
| B2 回执 TTL | 同一隔离进程，分别注入 applied/conflict 永久格式但带 60000ms TTL 的回执；实际 SessionHistoryWriter.apply 都 EffectNeedsReview，目标 DUMP 不变，原 TTL 仍为正，没有转成永久或写成功目标。通过。既有 test_session 的坏回执用例只设 hash 类型，没有 TTL 断言。本次 B1+B2 合计 2.266 秒，进程退出码 0。 |
| C1 时间整数精度 | 第二个独立隔离进程 PID 368，127.0.0.1:2276，版本同上。四个新动作通过实际 reviewed create/begin/sent 路径检查当前量级、14 位控制值及两个大整数；结果为两个精确控制组、两个确认的 C1 反例。本次 1.797 秒，进程退出码 0；该退出码表示探针完整记录了反例，不表示四种输入均保真。 |

既有 H1b 8 项与 H1c 6 项仅阅读，未重新执行、未运行全套。H1c.md:9 所记修订后两项 4.89 秒通过是主 Agent 的执行记录，不冒充本轮独立实测；本次独立证据为上述静态核对和新增探针。

## 接入条件与限制

1. **读取不授予权限**：delivery.py:89–97 的 inspect 只 GET/解码，不查 PTTL，也返回 token；prepared 可由 inspect 读到原 token。这是审查到的 API 边界。调用方必须仅用首次 create 成功返回的 token 和首次 begin 的确认结果发起传输；不能从 inspect 恢复发送权限。未来消费者还须通过自己的原子 sent/TTL/租约校验，不能仅凭可读 sent 快照执行目标。本轮未审查该尚未开发的消费者，也不据此宣称已有消费者缺陷。
2. **确认时间由调用方冻结**：当前 API 不能证明输入来自首次 ACK；也未检查 delivered_at_ms 与 begun_at_ms 的先后或时钟偏差。实际适配器必须冻结首次确认观察值，持久失败后仍使用同一值。时间证据丢失须待核对，不能以恢复时 TIME 或当前时间补造。test_delivery 的合成时间在 begin 前取值，仅证明保存/幂等规则，不证明真实传输时间语义。
3. **字节 CAS 与永久性条件**：本次不解决首次 CAS 前恢复相同字节的 ABA、缺失后创建再删除、无操作记录下 key 被驱逐/外部删除及 Redis 崩溃/复制持久性。current/legacy/missing 判断的保证是原子提交时的基线匹配；永久回执不设置 TTL，仍依赖部署保持证据。Lua/MSET 的普通原子路径不等同于所有故障的持久性证明。
4. **两项效果独立与接线待办**：session/global 的 pending 原子激活已核对；目标执行、全局记录冻结时间构造、效果租约/线程取消、扫描/Owner、候选最终 guard 与实际 transport 尚不在这五个文件中得到证明。本轮没有审整个 H1 或生产发送，也未启动应用。
5. **验证范围**：真实执行仅为本地 Redis 5.0.14.1、Python 3.10.20 与 redis-py 6.4.0 的两次短探针；没有 Python 3.13、Redis Cluster、Hiredis、真实网络丢包、资源耗尽或服务崩溃试验。故障响应丢失由受控包装注入；随机端口/PID 验证不等同于生产联调。
6. **写入与回退**：唯一持久变更为本报告，回退只移除本报告；无业务或测试修改，无 .env、真实 QQ、付费模型、提交、推送、部署或生产数据操作。没有全仓结构扫描；只检查本报告不超 400 行、无行尾空白和局部目录直属文件数量。

2026-10-05 22:55:13 +08:00 最终复核：七文件 SHA256 全部与表内一致；报告写入后为 75 行、0 行尾空白、history 审查目录仅 2 个直属文件。本句追加后报告为 77 行，仍在结构门槛内。
