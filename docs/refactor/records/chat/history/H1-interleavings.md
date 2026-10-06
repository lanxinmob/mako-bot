# H1 历史补记交错回归固化

## 开工与授权

2026-10-05 23:45:05 +08:00 开始本单元，重新读取 AGENTS.md 及六文档 project/development/plan/modules/status/audit，截断段于 23:48:31 +08:00 补读完成；没有更具体 AGENTS.md。用户已明确授权逐项固化 effects.md 两条 P3 建议，本单元是测试实现，不是独立评审，不为自己的新增测试出具独立通过结论。

唯一允许新增路径：`test/persistence/history_commit/test_interleavings.py`（不超过 400 物理行）和本记录。不得修改生产代码、已有测试、effects.md 或其他文档；主 Agent 同时只处理 Owner 单元测试/文档，写集不重叠。

保留契约：正常 transport sent、冻结计划和 ACK 毫秒值；原字节 CAS、永久 TTL、两类独立租约；取消 await 不释放活线程，稳定目标 ID/载荷与永久回执限制旧线程重放；全局部分追加的 started 证据不得当成功或重新追加，session 独立处理。当前 Owner 人工时间/abandoned 解码变化只作为运行基线，不在本单元验证或修改。

计划新增 A1/A2/A3/B/C 五个受控回归，直接导入实际 package 并使用既有 `test.autonomy.test_pending_atomic.isolated_redis` fixture。所有数据为合成样例，只写 fixture 随机端口/PID 核对后的 Redis；不启动应用、QQ、收费模型，不读取真实数据。

验证只运行新增文件一次；若失败，只修复本写集并复跑失败节点。不运行旧 6+3、旧基础、全套或全仓结构扫描。pytest 禁止 bytecode 和缓存插件；生命周期由既有 fixture 和有界事件屏障收尾。生产/已有测试/effects.md 的开工 SHA256 已记录，交付时复核。

## 证据与限制

已新增五个回归，直接导入实际 HistorySnapshots/计划/发送状态/租约/目标/worker/ChatRecord 与既有隔离 fixture。没有使用首项评审 probe 的内存 package、快照/会话替身或合成 sent 前置；fixture 经实际 read/create/begin/sent API 建立正常 transport 送达及两项 pending，固定 ACK 为 1791240000123、原时区偏移为 28800 秒。

| 新回归 | 固化的交错与断言 |
| --- | --- |
| A1 `test_a1_valid_state_replacement_between_get_and_eval_rejects_claim` | 包装认领 EVAL，确认输入是旧 sent raw 后，把记录换成可被实际 inspect 正常解码的 unknown/dormant。拒绝认领，替换 raw 原样保留、永久 TTL 不变，没有全局目标或回执。 |
| A2 `test_a2_sibling_update_blocks_stale_finish_then_same_token_settles` | 会话目标实际 apply 后，finish 的 GET/EVAL 之间实际认领 global；旧 raw CAS 收尾返回 False、整个兄弟更新保留。原 session token 随后重试成功，同 token 重复 finish 字节不变，global token/期限/尝试数和会话内容不变。 |
| A3 `test_a3_ttl_added_after_claim_refuses_settlement_without_mutation` | 已获得 global 租约后仅给隔离动作加入 60 秒 TTL。finish 抛 EffectNeedsReview，DUMP 与租约元数据不变、TTL 未取消，session 仍 pending，全局目标未写。 |
| B `test_b_cancelled_live_writer_arrives_after_new_holder_without_replay` | Event 屏障停在旧目标 apply 之前，取消 await 后旧线程仍存活且租约保留。仅调隔离租约期限到期，新持有者实际先完成；plan/ACK 相同、token 更新。释放旧线程后实际稳定 ID 目标返回 already_applied；显式旧 token finish/defer 均拒绝。新任务 raw/结果/token、回执与唯一全局记录不变，毫秒时间为 2026-10-06 06:40:00.123000，两份证据永久。finally 释放并有界等待该线程。 |
| C `test_c_partial_global_append_lost_error_keeps_started_and_session_independent` | 仅替换本次发送给隔离 Redis 的内存 Lua，在真实 RPUSH 后返回 ResponseError，再由客户端包装丢弃错误回包并抛连接异常。首次 worker 为 unavailable/retry_wait，精确 started:digest、唯一追加记录和永久回执保留；调隔离 retry 时间后，未修改的实际 writer 报 target_incomplete，任务终结 needs_review、尝试数/token 更新，无重复追加。session 元数据不受影响并随后实际完成，global 状态/started/记录继续不变。 |

仅第一次运行新增文件，命令如下（仓库根；同时设置 AUTONOMY_ENABLED/PROACTIVE_ENABLED/REDIS_REQUIRED/LLM_REQUIRED=false，PYTHONDONTWRITEBYTECODE=1）：

```powershell
& '..\.refactor-snapshots\validation-py310\Scripts\python.exe' -B -m pytest -q -s -p no:cacheprovider test/persistence/history_commit/test_interleavings.py
```

实际结果：**5 passed in 8.16s，退出码 0**；shell 9.585 秒。Python 3.10.20、redis-py 6.4.0、pytest 8.4.2，五个 Redis 均为 5.0.14.1。没有失败节点，因此没有任何复跑、额外收集运行、旧 6+3/基础/全套运行。

| 用例（运行顺序） | 随机回环端口 | fixture PID |
| --- | ---: | ---: |
| A1 | 7993 | 43000 |
| A2 | 7834 | 63396 |
| A3 | 10933 | 17652 |
| B | 10938 | 39508 |
| C | 3626 | 61580 |

既有 fixture 在写入前核对 INFO process_id 与 Popen PID，save/appendonly 关闭、Windows 隐藏进程，finally 关闭客户端并终止/等待自己的进程。23:52:54 +08:00 查询以上五个 PID，均已无进程。没有连接真实 Redis 或清库。

## 运行基线与并行变更

用户在新增文件运行完成后补充：主 Agent 于 23:48 前完成最后两项共享解码防御，随后冻结生产文件。开工哈希核对确实只有 delivery.py/tasks.py 漂移：

| 文件 | 23:46 开工 SHA256 | 23:52:54 交付核对 SHA256 |
| --- | --- | --- |
| src/services/persistence/history_commit/delivery.py | 2dd470761866b443a609d1ff19628b48279e6245430031d8e79861a6a247cff9 | c2fc12bfd8e142ac5b6cfef939e5669ebce4d3ebd6fd24c52375338d3f1ccf68 |
| src/services/persistence/history_commit/tasks.py | 2af1adb654640036269bec49326beec578993e12182cb8f41ceed070ac6a87b4 | 7e2cee201060e906806252be637c33aaec3bc4c3c903ffac56801bee78678e44 |

当前 delivery.py:50 对人工分支要求 delivered_at_ms 字段显式存在且 null；tasks.py:116–117、:131–132 的 claim/_settle 另要求 confirmation_source=transport。它们属于主 Agent 并行修改，本单元没有撤销、覆盖或修改。这五项测试的全新 Python 进程在补丁之后启动，fixture 实际断言正常 transport 和冻结 ACK；正常路径通过不构成人工分支独立验收，不以初始哈希冒充执行版本，也不为哈希漂移重跑旧检查。

运行所用其他相关版本如下，开工/交付哈希相同：

| 文件 | SHA256 |
| --- | --- |
| src/services/persistence/history_commit/snapshot.py | 11da116fb9bd56ac45879e1c49bd7c8d1c12f41d5fed48c4c77ec51ffb01a5a3 |
| src/services/persistence/history_commit/plans.py | e3387048a3c495ce70599c43be9d6122eecf56b41ee518ba7c8e34f721c455c1 |
| src/services/persistence/history_commit/delivery_scripts.py | 47f8bc7d1b5001de810ada32bd935fea79ff69b0329fce625add7761e20bc68e |
| src/services/persistence/history_commit/task_scripts.py | 6f3053c4e3987a52b4e5c786af5bf6b05dcd08b25d939c660b9786837801da38 |
| src/services/chat/history_delivery/targets.py | e962cdbada40e35679ebc0614fcd4cddb62521f5246515725ee1a89f5fc72343 |
| src/services/chat/history_delivery/worker.py | 4efb3c87c56b2fb6152d4bee2bf77a2a94e0f11781b6755a8f3435202278441f |
| src/services/persistence/effects/store.py | 89bfd1da9c08ef4a2d5caa94228bb445d353687e5ed8fffaacbcbeed6b8a52fd |
| src/services/persistence/effects/scripts.py | b876063d9b9084501be12e45d7aefa52a2f13843de0c49b92740481ce243a204 |
| test/autonomy/test_pending_atomic.py | d9720f49df142b9414423dcf3a90ccc463fa6d74fc78c9fd9aec67e2a2751d6c |

新增测试文件为 277 物理行，SHA256 `ed8640d313e716b68e196a9c756c6f4496aee8f1eb5e1d9ae307a91d841825fe`。交付核对的 17 份保护文件中，仅上述主 Agent 两份生产文件变化，另外 15 份保持开工哈希；包含本项依赖、五份既有基础/task/worker 测试及隔离 fixture。effects.md 保持 `fb764a2761baf790e3ba3fc2c846259cca0203cc3bab3c4df63d885bc1ca96a7`，原评审未被本单元改写。

## 剩余限制与交付

- 本单元完成两条 P3 建议的测试固化与一次实际运行，是实施者验证；没有声称新增测试已获独立评审、完整 H1 验收或 Owner/生产入口/scan 核对完成。
- 受控 GET/EVAL 包装、隔离 TTL/期限调整和内存 Lua 故障注入用于构造确定性交错；不模拟系统时钟，不修改落盘脚本，不等同于真实网络断连、Redis 崩溃/复制/资源耗尽验证。测试仅覆盖 normal transport，人工时间、abandoned、发送/模型能力和恢复扫描不在范围。
- 仅运行 Python 3.10.20；未新增 Python 3.13、Hiredis、Cluster 或生产持久化证据。永久回执不被删除/驱逐、稳定输入和新旧写入者统一的既有限制继续保留。
- 没有启动应用、QQ、收费模型或读取真实数据，没有改生产代码、已有测试或其他文档，没有提交、推送、部署、清库或全仓扫描。pytest bytecode/cache 已关闭；Redis 临时目录属于既有 fixture 生命周期。
- 仅局部统计：新增测试 277 行，history_commit 测试目录 7 个直属文件，history 记录目录 6 个直属文件，均未越过 400 行/10 文件阈值；这不是全仓结构结论。
- 本单元改动路径只有 `test/persistence/history_commit/test_interleavings.py` 与 `docs/refactor/records/chat/history/H1-interleavings.md`。回退只移除这两份新增文件，保留历史状态、永久回执、主 Agent 并行变更、其他 Agent 改动与原评审结论。
