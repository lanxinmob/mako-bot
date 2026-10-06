# H1d 第一项：历史租约、目标与消费者独立核对

## 范围与结论

- 2026-10-05 23:26 +08:00 开始，未参与本项实现。重新读取 AGENTS.md、六文档 project/development/plan/modules/status/audit、B3.md、H1d.md 和基础 history/synthesis.md（含 C2 修复追加）；另读取 migration.md。仓库仅有根 AGENTS.md，父工作区无该文件。已有草稿保留。
- 本评审唯一可写、唯一持久改动：`docs/refactor/records/review/resumed/history/effects.md`。核心代码只读 tasks.py、task_scripts.py、targets.py、worker.py，测试只读对应 test_tasks.py、test_worker.py；必要依赖只读 delivery.py、plans.py、session.py 和既有全局 EffectWriter/模型依赖。隔离验证仅提取已有 isolated_redis fixture，不导入其自主业务模块。
- 保留 sent、完整冻结计划、永久 TTL 与原字节 CAS 才可认领；session/global 独立 token/租约/结果；旧 token 不收尾新租约；取消不提前释放活线程租约；目标重试保持原参数与 ACK 时间；会话冲突保留新历史，全局独立；目标未知写入依永久回执保守收尾。
- **结论：下列当前哈希下，本分项附限制通过。未发现新增 P1/P2 实现缺陷，无本分项必要业务修复；P3 为持久测试证据补充建议。** 新短 probe 验证了原检查未覆盖的 CAS 交错、认领后 TTL、取消活线程与新持有者重叠，以及实际部分追加的错误回包丢失。
- 不验收生产 runtime/pipeline/transport 接线、Owner 设计/代码/新时间状态、scan/发现、完整 H1、生产持久性或真实 QQ 行为。主 Agent 同时推进的 Owner 工作不属于本哈希结论。
- HEAD `8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9` 只是原基线；本项为未提交工作区实现，结论绑定 SHA256。23:34:28 +08:00 复核时，九个核心/基础文件哈希与初读相同。

## 实现与测试版本

| 文件 | 物理行数 | SHA256 |
| --- | ---: | --- |
| src/services/persistence/history_commit/tasks.py | 137 | c4d2324941d2fc8934d1b2b56d41e29ca1a9fda34cfa1a764d32116330904d59 |
| src/services/persistence/history_commit/task_scripts.py | 51 | 6f3053c4e3987a52b4e5c786af5bf6b05dcd08b25d939c660b9786837801da38 |
| src/services/chat/history_delivery/targets.py | 31 | e962cdbada40e35679ebc0614fcd4cddb62521f5246515725ee1a89f5fc72343 |
| src/services/chat/history_delivery/worker.py | 67 | 4efb3c87c56b2fb6152d4bee2bf77a2a94e0f11781b6755a8f3435202278441f |
| test/persistence/history_commit/test_tasks.py | 117 | 4c7abb7356a98ebdea710cf07d9cdada373f0ee611c71d1b4d100e3d4b1cb50e |
| test/chat/history_delivery/test_worker.py | 92 | 387592d3cbf6d18fe40754fe5c966824dd53bd2b9e73145bd92b3a41870c5737 |
| src/services/persistence/history_commit/delivery.py | 122 | 9266957d3eae1aa4fb17109f34cb0b3f7abd70c1012d284cb21db35ab30f0c25 |
| src/services/persistence/history_commit/plans.py | 117 | e3387048a3c495ce70599c43be9d6122eecf56b41ee518ba7c8e34f721c455c1 |
| src/services/persistence/history_commit/session.py | 65 | e3b121e2cfafbc44b6a4eca4c3de5e19c31d5bfc0454e1a034637d6502b8ff83 |

依赖与基础证据也绑定本次读取内容；其哈希不代表重新验收整个既有模块。

| 依赖/证据 | SHA256 | 本次使用范围 |
| --- | --- | --- |
| src/services/persistence/effects/store.py | 89bfd1da9c08ef4a2d5caa94228bb445d353687e5ed8fffaacbcbeed6b8a52fd | 全局 writer、异常分类和载荷摘要 |
| src/services/persistence/effects/scripts.py | b876063d9b9084501be12e45d7aefa52a2f13843de0c49b92740481ce243a204 | history 分支的 started/终结回执 |
| src/models/schemas.py | f39813fef21bca96c427c6121ab097abd8ad08d31c474b6aaa857815a6c1af1c | ChatRecord；probe 仅载入其及 writer 导入所需 OutboundMessageRecord 的原 AST 节点 |
| test/autonomy/test_pending_atomic.py | d9720f49df142b9414423dcf3a90ccc463fa6d74fc78c9fd9aec67e2a2751d6c | 仅 :15–48 的隔离 fixture |
| docs/refactor/records/review/resumed/history/synthesis.md | b422f6dafccf0e56e9cab775e1dd65380a0c7897cfe0b4261bb100d31bde2c86 | 基础 CAS/回执/C1/C2 独立证据与既有限制，107 行 |

## 契约核对

| 项目 | 当前依据与判断 |
| --- | --- |
| sent + 永久 TTL + raw CAS | tasks.py:86–119 先解码完整计划/绑定和任务，再认领；task_scripts.py:4–13 原子检查类型、原字节、PTTL=-1、sent。GET 结果本身不授权写入。A1 在 GET 后改成合法 unknown/dormant，Lua 拒绝且保留替换字节；A3 在认领后加 TTL，finish 拒绝且 DUMP 不变。 |
| 任务与元数据 | tasks.py:41–75 校验两类元数据、严格整数、token、attempts、期限、状态与结果对应关系；pending/dormant 不接受旧租约元数据。坏证据关闭消费，不静默补默认租约。验证完整 envelope 可能使坏兄弟元数据关闭整条动作，这是保守策略，不等于 session 业务冲突阻断 global。 |
| 独立租约与旧 token | task_scripts.py:24–30 只有 pending/到期 leased/到期 retry_wait 可认领，生成独立 task token，累计尝试次数；:32–45 比较当前 token、有效期限与结果。tasks.py:124–129 同时绑定原 plan 和原 ACK 时间。结果幂等不延长租约/退避；旧 token 不能收尾新持有者。兄弟并发更新导致 raw CAS 不匹配时返回未确认，不覆盖兄弟任务；A2 验证随后用同 token 重试可安全收尾。 |
| 取消与迟到线程 | worker.py:20、25、43 的存储/目标都在线程执行，取消 await 无法撤销线程；CancelledError 不被 :28–39 或 :45 捕获，因而不走主动释放/退避。B 在旧目标线程仍阻塞时取消，然后模拟到期，让新持有者先完成；旧线程随后调用实际全局目标仅返回 already_applied，未改新任务结果。取消 claim/settle await 的长期恢复仍依原租约/幂等结果，非无限等待线程退出。 |
| 稳定目标参数与 ACK 时间 | plans.py:39–77 校验冻结内容与裁剪/保留/时区参数，:96–99 派生 session/global 独立 effect_id。targets.py:19–23 从同一计划取会话基线与保留数；:24–31 显式传入原 delivered_at_ms，整数 timedelta 保留毫秒，以冻结偏移转成旧兼容 naive 时间。ChatRecord 的 datetime.now 默认被显式 time 覆盖，nickname 的 None 默认稳定；没有随机 ID、重读当前设置或当前时钟。B 核对 2026-10-06 06:40:00.123000 与同一序列化记录不变。该时间是合成 ACK，不证明生产 ACK 观察来源。 |
| 会话冲突与全局独立 | session.py:59–60 抛 HistoryConflict，worker.py:28–29 将 session 标 history_conflict；:50–67 逐目标认领，不按兄弟业务结果停全局。test_worker.py:19–31 使用实际目标检查新会话原样保留、global 一条原时间记录。该项本轮只读、不复跑；会话原始 CAS/永久冲突回执沿用 synthesis 基础独立证据。 |
| 响应丢失与永久回执 | EffectWriter/store.py:37–71 绑定稳定 effect_id、完整记录、目标和保留参数；scripts.py:9–15 先查结果，:17–23 在 RPUSH 前存 started，:60 保存终结摘要。worker.py:30–35 只对连接/超时未知退避；started 对应 EffectIncomplete 转 target_incomplete，不再追加。test_worker.py:35–61 覆盖两目标成功后丢响应和 finish 丢响应（本轮不复跑）；新 C 补实际部分 RPUSH 的错误回包丢失，重试进入 needs_review，原永久 started 与列表均不变。 |
| 收尾失败与隔离 | worker.py:42–48 收尾未确认不会把任务假报 complete，也不重发消息；:60–63 存储故障按目标记录 unconfirmed 并继续其他目标。目标异常映射为有限原因码，EffectIncomplete 在宽泛 EffectNeedsReview 之前处理。消费者仅持有存储/目标依赖，不持有模型或 QQ 发送依赖；实际 runtime 接线不在本审查范围。 |

## 分级意见与必要修复

| 优先级/处置 | 具体结论 |
| --- | --- |
| P1：新增实现缺陷 0 | 本范围未发现重复全局追加、覆盖较新会话、unknown 授予历史权限或旧 token 覆盖新租约的可复现缺陷。短 probe 不证明 Redis 崩溃/复制/资源耗尽或真实 QQ exactly-once。 |
| P2：新增实现缺陷 0 | 本分项没有阻断通过的业务修复。永久回执及冻结参数是迟到线程安全的前提，不能清除证据或混用旧直接写入者；这些基础限制继续保留。 |
| P3：持久测试补充建议 | 当前两个专属测试文件没有固化 A1/A2/A3：GET→EVAL 替换、兄弟更新撞收尾 CAS、认领后 TTL 的交错。本次短 probe 已补独立证据；建议后续获准修改测试时加受控回归。 |
| P3：持久测试补充建议 | 当前取消测试先等旧线程结束再到期，目标丢响应测试在 actual.apply 成功后主动抛异常。建议固化 B 的新持有者先完成/旧活线程迟到，以及 C 的实际部分追加+错误回包丢失→target_incomplete；不要只断言“无重复”而漏掉永久 started、任务原因和兄弟状态。 |
| 必要修复 | 当前哈希下无本分项必须修改的代码。以上 P3 是证据持久化建议，不是新发现的 P1/P2，也不要求为此重跑现有 6+3、旧基础或全套。 |

## 新增短 probe 与证据归属

仅运行一次新增内存脚本：`../.refactor-snapshots/validation-py310/Scripts/python.exe -I -B -`，stdin 执行，不保存脚本或 pycache。实际载入原 tasks/task_scripts、targets/worker、plans/delivery、EffectWriter/store/scripts；未导入项目包入口、应用或定时任务。公开 delivery.create/transition 未调用，已送达 envelope 为隔离合成前置条件，不能据此证明生产激活。

遵守额外代码读取边界：HistorySnapshot/decode_history、valid_id 和 SessionHistoryWriter/HistoryConflict 使用内存替身；snapshot 替身仅用于本次固定 missing/list[dict] 样例，不承担坏快照验证；session.apply 替身一旦被调用即失败，故本次没有会话目标执行证据。delivery_scripts 使用禁止执行的占位值，未读取或执行该文件。ChatRecord/OutboundMessageRecord 使用实际模型定义 AST，未替换全局序列化实现。真实 task Lua、全局 Lua、异常分类、租约解码和 asyncio.to_thread 参与执行。

隔离生命周期原样取自既有 fixture：随机回环端口，INFO server/process_id 与 Popen PID 一致才写；关闭 save/appendonly，临时目录，Windows 隐藏窗口；finally 关闭客户端并终止/等待自己的 Redis。Python 3.10.20 / redis-py 6.4.0 / Redis 5.0.14.1，127.0.0.1:11242，PID 37276。退出码 0，shell 3.501 秒，脚本内部 2.073 秒；23:34:28 查询该 PID 已无进程，临时目录由 TemporaryDirectory 清理。

| 新探针 | 实际结果与故障模型 |
| --- | --- |
| A1 | client 包装在实际 claim EVAL 前将 sent 合法替换为 unknown/dormant，返回 None、替换 raw 不变；不根据旧 GET 授权。 |
| A2 / A3 | session finish 的 EVAL 前认领 global，旧 raw finish 返回 False、兄弟字节保留；随后同 token finish 成功且 global token 不变。再给动作添加 60 秒 TTL，global finish 抛 EffectNeedsReview、DUMP 不变且 TTL 仍存在。只在隔离数据中加入竞态/TTL。 |
| B | threading.Event 暂停实际 global apply 前的旧线程；取消 await 后它仍存活，租约保持 leased。仅把隔离租约期限调到 Redis 当前时间前，随后新租约先完成；释放旧线程后实际目标返回 already_applied。一条全局记录、毫秒时间和新任务 raw 不变，动作/目标回执 PTTL=-1。没有等待实际 120 秒，也没有用该操作模拟生产时钟修改。 |
| C | 仅把本次送往隔离 Redis 的内存全局 Lua 在 RPUSH 后/LTRIM 前插入 error_reply；真实 ResponseError 被客户端包装丢弃，改抛连接异常。首次消费者返回 unavailable，保留永久 started 和一条该效果记录；仅把隔离 retry 时间调到期，再用原未修改 Lua 接手，返回 target_incomplete 并终结 needs_review，无重复追加，session 保持 pending。没有更改落盘 Lua或复用真实业务数据。 |

主 Agent 的现有检查不冒充本次独立运行：按用户提供及源码证据，6 个 task + 3 个 worker 首轮 8 通过、1 失败为 JSON 字段顺序；当前失败项已改为解析后语义比较，并补全局 response-loss 后定向通过。H1d 记录另有发现/接线检查，这些均不纳入本项执行数量或验收。本轮没有运行这 9 个检查、旧基础测试、全套、全仓结构扫描或其他 Agent 的 probe。

## 限制与交付

- 会话目标适配结论来自当前 session.py/targets.py/worker.py、两个获准专属测试的只读检查；基础快照/CAS/永久回执结论沿用 synthesis 独立证据，没有读取基础专属测试或重复其 Lua 验证。新 probe 的内存替身与合成 sent 不证明真实 package 导出、输入同请求绑定、实际 ACK 冻结或入口契约。
- 不验证 Python 3.13 的新增交错、Hiredis、Redis Cluster、真实网络丢包、Redis 崩溃/复制/资源耗尽/持久配置，也不证明永久证据不被删除/驱逐、ABA 可识别或后台恢复时延。receipt 必须保持，旧线程可以在租约到期后继续触达目标，其安全依赖稳定 ID/参数和目标幂等。
- 所有短 probe 通过仅支持本 H1d 第一分项；完整 H1 仍需独立核对获准生产接线、Owner 和 scan 范围及综合验收。新 Owner 时间状态没有在这里被评审或批准。
- 本评审没有改代码/测试/其他文档，没有读取秘密或真实聊天数据，没有启动应用、模型、QQ，也没有提交、推送或部署。其他 Agent 并发改动不算本评审改动。
- 回退仅移除本报告；不 reset/stash/clean、不撤销其他 Agent 的工作、不删 Redis 原证据。唯一改动报告路径：`docs/refactor/records/review/resumed/history/effects.md`。

交付复核：2026-10-05 23:38:38 +08:00，上表九个实现/测试、四份依赖/fixture 及 synthesis 共 14 份 SHA256 全部吻合；报告 82 行、无行尾空白，审查目录 4 个直属文件（追加本句前）。仅局部报告检查，未运行全仓扫描。
