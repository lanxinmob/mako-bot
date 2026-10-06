# P4 提醒存储接入契约独立评审

## 开工与结论

- 读取时间：2026-09-24 11:30–11:38（Asia/Shanghai）；评审对象为当前未提交工作区，HEAD 为 `8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9`。
- 已重读：根 `AGENTS.md`、`docs/agent/project.md`、`docs/agent/development.md`、`docs/refactor/plan.md`、`docs/refactor/modules.md`、`docs/refactor/status.md`；仓库内 AGENTS 文件枚举仅发现根说明。
- 批准依据：本次用户明确批准 P1–P6；`docs/refactor/status.md:9–11`、`docs/refactor/records/chat/B3.md:62–73,114–130`。配置拆分继续暂停。
- 本次唯一允许写入路径：本文件。业务代码、测试、状态总表与他人草稿均不修改。评审由未参与本单元实现的当前评审者完成，不冒充多 Agent 综合验收。
- 保留契约：旧正文兼容、稳定业务身份、Redis 故障关闭、取消使旧源失效、unknown 不自动重发、晚确认不删除新版。
- 验证范围：逐行静态核对、读取现有测试、一个无业务导入的 AST 参数边界探针及文档结构检查；没有运行 pytest、Redis、QQ、应用启动或读取 `.env`。

**结论：发现一项新 API 输入契约缺陷（F1）；其余下列 C1–C7 是接线验收条件，不把旧插件尚未接入记为新增 bug。当前存储基础不能代表 P4 端到端完成。**

`docs/refactor/records/chat/B3.md:5–16` 明确本轮仅交付存储单元。其历史测试数字是实现记录，本评审没有复跑，也没有将其改写为独立测试通过。

## F1 / P2：存储接受发送状态模型拒绝的身份值

位置：`src/services/persistence/reminder_state/store.py:20–21,44–46,54–55,63–66`；对照 `src/services/delivery/state/models.py:28–31`。

create/replace/bind_bot 只检查 bot_id 是非空字符串，不检查纯空白和 512 字符上限；job_id 检查长度但也接受纯空白。DeliverySpec 对 bot_id/business_id 要求 `.strip()` 非空且长度不超过 512。

最小触发：`create(record, bot_id=" ")` 或 `bot_id="9" * 513` 通过源 API 校验；Lua 在 `reminder_state/scripts.py:75–80` 将其持久化。随后用同一 bot_id 构造 DeliverySpec 会抛 `ValueError`，不能进入 claim。迁移项 `bind_bot(snapshot, " ")` 也会在 `scripts.py:85–88` 固定该值，正确 bot 随后被 `wrong_bot` 拒绝；replace 同样不能换回正确 bot（70–71 行）。这不是旧插件未接线，而是两个新 API 的可接受输入集合不一致。

本轮实际探针：用 AST 单独加载 ReminderStateStore 类，将 `_call` 替换成仅返回标记的函数；独立加载只依赖标准库的 DeliverySpec。无 Redis、无模型/配置/插件导入。两例输出均为 `source=accepted_before_redis, delivery=rejected`（长度分别 1、513）。持久化后果来自上述 Lua 静态路径，未声称运行了 Lua。

处置要求：在写入前统一 bot_id 与 business_id 的身份约束，拒绝纯空白/超长值；不要靠事后构造 DeliverySpec 才报错，也不要静默 strip 后改变已存身份。增加上述边界的窄断言即可，不需要全套测试。正常 OneBot self_id 通常不会触发本项，因此不定为线上发送回归。

## C1：旧记录迁移必须保留原始正文和过期项

证据：

- 旧格式在 `src/models/schemas.py:51–58`，没有 bot/revision；旧仓库 `src/services/persistence/reminders.py:13–18,21–26` 使用 `reminders` hash 并支持内存后备。
- 新 load 返回原始字符串和 revision；`reminder_state/models.py:21–31` 在 raw 上计算 SHA1。
- `reminder_state/scripts.py:25,41,67–80` 用 Redis TIME 判断未来，仅无 revision/meta 项可 migrate，迁移原样保存 raw；`store.py:59–61` 固定迁移 grace=300。
- 现有 `test/delivery/state/test_reminder_source.py:139–153` 包含未来/过期迁移及首次绑定用例；没有覆盖整个启动恢复入口。

接线要求：枚举候选后，必须由新 store.load(id) 取得实际 Redis 快照再 migrate_future；不得将旧仓库反序列化对象重新 JSON 编码后当作 expected/raw。排序、空白、created_at 等差异会改变摘要。无法解析/身份不匹配项应保留待核对，不能删除或自动补发。

`overdue`、`already_versioned`、`changed` 必须分支处理；读取阶段“未来”不代表写入时仍未来。过期旧记录原样保留，已有版本不能重新初始化。内存后备记录不能授权后台发送。

迁移切换时须停止旧写入口：旧 save/delete（`persistence/reminders.py:13–18,52–55`）只动正文，不同步 revision/intent。未来仍允许旧 ReminderBook 写入会破坏元数据一致性；这是上线切换条件，当前并存本身不计新增 bug。

## C2：bot 绑定必须先于构造动作身份

证据：`reminder_state/scripts.py:81–88` 检查当前 meta/revision/upsert 并原子固定 bot；`store.py:49–57` 与 Lua 70–71 行阻止替换已绑定 bot。当前插件 `src/plugins/chat/reminders.py:52` 使用无 ID 的 get_bot()。

新建取事件 self_id 并保存为固定字符串。恢复旧项先迁移，再用实际可用 bot 调 bind_bot；必须消费成功返回的 snapshot 或重新 load，不能继续使用 bot_id 为空的迁移快照。两个 bot 竞争时，失败方停止，不生成另一 bot 的 DeliverySpec。

实际发送应按持久化 bot_id 选择 bot，并核对 bot.self_id。绑定 bot 离线时保留任务，不换 bot 生成新动作；否则 `delivery/state/models.py:43–46` 中包含 bot 的 action_id 会让同一提醒变成另一动作。

特别边界：`delivery/state/scripts.py:31–40` 只核对正文摘要和 revision，**不读取提醒 intent 的 bot_id**。bind 不修改 raw/revision，所以不能指望通用 claim/begin 替调用方纠正错误 bot。必须有可信的提醒 spec 构造入口；不能让调用方自由传 bot/target/source 参数。

## C3：修改保持业务 ID，重启保持 revision

证据：旧 `delivery/reminder.py:56–58` 由群/用户/时间生成 ID；旧插件 `reminders.py:92–112,226–240` 修改时间会建立另一 ID。新 `reminder_state/store.py:49–57` 明确不允许 replace 改 reminder_id/session/group/user。

未来 MODIFY 必须使用当前 reminder_id，只改变内容/时间并由 store 产生新 revision。不能继续用 generate_job_id(new_time) 构造替换记录；否则新 API 明确拒绝，若绕为 create 则留下两个业务源。

重启恢复必须使用持久化 revision；旧插件 `reminders.py:129–146` 的随机 version 只能退出授权链，不能作为 DeliverySpec.revision。相同 ID/revision/bot/目标得到相同 action_id，payload 改动不改变动作身份但会触发冻结 spec 冲突（`delivery/state/models.py:43–53`、`scripts.py:43–49`）。

新建 ID 须在一次业务创建的持久化结果核对期间保持不变。仍采用时间派生 ID 时，同群同用户同时间的重复创建要处理 `exists`，不得覆盖；若以后改 UUID，也不能在响应丢失重试时另造 UUID。显式重建已取消 ID 会获得新 revision（`reminder_state/scripts.py:28–31,74`），不能将它当自动重试 unknown 的工具。

## C4：先保存意图，APScheduler 只是缓存

证据：`reminder_state/scripts.py:73–80` 同次 Lua 保存源、revision 和 upsert 意图；89–95 行删除有效源并保留 cancel 意图。当前插件 `reminders.py:94–112` 则先 add_job 再保存，202–209 行先移除 job 再删源。

创建/修改必须先确认 mutation.ok，再按返回 snapshot 注册 job；异常是“结果未知”，不是“未保存”。注册失败保留已保存意图，后续按相同 ID/revision 恢复，不重新 create/replace 换 revision。取消必须先确认源失效，再清缓存，JobLookupError 不代表取消失败。

恢复器须读取 upsert/cancel 意图，核对当前源和 revision 后投影到本地 scheduler；`load()` 只返回 snapshot、源不存在返回 None（`store.py:34,41–42`），**不能通过 load 看见取消墓碑**。后续需要受控枚举 intent 的入口或等价恢复协议；这是尚未交付的接入能力，不是 load 的读语义 bug。

交错约束：A 保存 r1 后延迟 add_job；B 保存 r2 并注册；A 最后覆盖缓存时，r1 callback 必须被源校验拒绝，恢复器最终要重新注册 r2。相反，旧取消的迟到 remove_job 不能永久移除新建版本的 job；只按 job_id 移除不够，需要串行投影或版本检查和再协调。不要用“源 CAS 正确”推断调度缓存已经收敛。

新建 grace=60、迁移 grace=300 的意图值来自 `store.py:19,59–61`；截止时间应由固定 remind_at_ms 与 grace_seconds 推导，不能每次恢复重置为 now+grace。旧插件启动跳过到期项（124–126 行），应继续区分过期旧记录和已注册 job 的 misfire 宽限，不自行扩大补发策略。

时间解释要统一：`store.py:27` 对 naive datetime 使用进程本地时区；旧插件直接把 datetime 交 scheduler（97、133 行）。接入前须验证进程与 scheduler 时区对应同一时刻；Redis TIME 只能统一比较时钟，不能修正 datetime 解释错误。

## C5：源绑定与冻结发送内容必须来自同一快照

提醒 spec 必须固定如下映射（依据 `delivery/state/models.py:14–26`、`reminder_state/scripts.py:53–60`）：

| DeliverySpec 字段 | 来源 |
| --- | --- |
| kind / business_id / revision | reminder / record.reminder_id / snapshot.revision |
| bot_id / target_type / target_id | snapshot.intent.bot_id / group / str(record.group_id) |
| source_key / source_field | reminders / record.reminder_id |
| source_digest / revision_key | snapshot.digest / REVISION_KEY |
| payload / valid_until_ms | 同快照确定的发送正文 / 固定到期与宽限截止 |

`ReminderSnapshot.digest` 是 raw 的 SHA1，DeliverySpec.digest 是完整 spec 的 SHA256；两者不可互换。`DeliverySpec` 允许四个 source 字段全空（models.py:38–40），提醒编排必须禁止这种用法。完整 source 绑定才能让排队后取消/替换在 begin 处得到 source_changed。

通用状态仅证明源未变，不证明 payload 是源内容的正确格式化结果，也不检查当前时间已到 remind_time；调用方必须固定格式和到期判断。不能把旧 callback 捕获的 message 与新 load 的 revision/digest 混用，不能按当前正文重组旧已冻结动作。

旧插件正文含前导空格与可选 at-all（reminders.py:53–56），恢复参数固定 False（139 行）。接入需明确保留该格式，不能临时新增非持久化的 at-all 开关。

现有测试 execution helper（`test/delivery/state/test_reminder_source.py:23–27`）使用 `valid_until_ms=2**52`，只适合状态测试；不能照搬为生产提醒截止规则。

## C6：取消反馈必须区分未检查、未开始、发送中与未知

证据：`reminder_state/scripts.py:21,43–65,89–95` 返回观察到的 phase，但不改动作 ledger；取消正文让后续 begin 源校验失败。已经 begin 的传输不能被 HDEL 撤回。

| 返回 delivery_state | 允许的反馈/后续 |
| --- | --- |
| uninspected | 未检查动作；不能声称肯定没发送 |
| not_started / queued | 在动作键正确前提下，已撤销后续发送授权 |
| sending / unknown | 后续已取消，当前可能已经送达、不能撤回或自动重发 |
| sent | 已送达事实保留，取消只撤销未来执行 |

动作键必须由**被替换/取消的旧快照**固定身份计算，再用 `DeliveryStore.key(spec.action_id)` 转成完整 key；不能传 action_id 裸摘要、新版 key 或任意合法格式 key。`store.py:22–23` 只检查 key 格式；Lua 只在该 key 存在时验证归属（44–61 行）。若真实旧动作正在 sending，却传入另一不存在的合法 key，会得到 not_started。这里将“正确派生键”列为调用前置契约，不把调用者传错 key 的场景冒充当前线上回归；接口可进一步内聚派生以降低误用。

cancel/replace 默认不传 key 得到 uninspected，业务层不得将它转换成“旧提醒一定未发”。Redis 异常、mutation.ok=False 或 changed 均不得发送成功取消/修改文案。成功返回的新 snapshot 可用于刷新状态，不能据此在冲突时自动重放用户修改。

## C7：实际传输与晚确认必须保留同一个动作/token

证据：`delivery/state/attempt.py:23–48` begin 成功后才调 callback；要求返回 literal True；ACK 与 state_confirmed 分开。`delivery/state/scripts.py:63–81` token fencing，unknown 可接收同 token 晚到 sent，但 sent/unknown 不可重新 claim（43–49 行）。

claim 可以在进入 dispatcher 前做，begin 必须在实际 send 回调内做；不能先 begin 再调用会排队的 send_to_group。当前 helper 把 transport 封在内部 callback（`src/services/delivery/dispatcher.py:282–291`），接线时需使用可包裹该边界的调度路径，保留群出站观察。

OneBot 原始字典不能直接返回给 DeliveryAttempt（其 `is True` 判断会记未确认）；在传输边界核验 ACK 后转成 bool。不能把共享 dispatcher 的一般“回调完成”语义等同于持久化 sent。

确认送达后用原 snapshot 和原 action key 调 complete。`reminder_state/scripts.py:41,53–60,90` 同时要求源 raw/revision、动作归属/摘要和 sent；`33–37` 支持同动作重复 complete。ACK 已收到但 mark_sent 未确认时，不绕过 complete 条件清理源，更不能重发。

两条关键交错：

1. r1 begin → replace 为 r2 → r1 晚到 ACK/mark_sent：r1 动作允许记 sent；complete(r1) 必须 changed，r2 留存。现有 `test_reminder_source.py:112–124` 已有对应断言。
2. r1 begin → cancel(r1) → 显式重建 r2 → r1 晚到 ACK：旧动作证据保留，complete(r1) 不能清 r2；不能用“job_id 一样”代替 revision/raw CAS。现有 67–94 行分别覆盖排队取消与发送中取消，但未形成这一完整晚确认重建交错。

cancel 没有把动作 ledger 变成 cancelled；旧 queued 会因源不存在/改变不能 begin。不要因此额外用无 token 的 ledger 覆盖，也不要清掉旧 sent/unknown 证据。完成墓碑、意图保留与幂等补记的后续清理属于 P5/P6，不在本次只读评审中实现。

## 接入时最小验收清单与本轮限制

后续只需针对新增接线风险补窄用例，不重复已经覆盖的全部状态测试：

- 存储写成功但响应丢失/注册失败：重启仍用同 ID/revision；不另建动作；取消意图最终移除缓存。
- 两 bot 同时绑定旧未来项：只由胜者构造 spec；绑定 bot 离线不换 bot；F1 非法身份写前拒绝。
- r1/r2 scheduler 投影乱序及迟到 remove：旧回调拒发且当前有效任务最终仍可调度。
- dispatcher 排队期间取消/修改、同 token begin 响应丢失：零错误传输；不因重试刷新身份。
- cancel → recreate → 旧 ACK：新版源不被删除；ACK 后状态补记失败不重发；发送反馈准确区分 uninspected/unknown。
- 生产 spec 的真实截止时间、时区、冻结正文与源摘要映射，不能沿用测试 helper 的远期截止。

本轮未验证实际 Redis Lua 执行、双进程、APScheduler 集成或 QQ 行为；仅静态确认已有防护与列出的条件。没有业务修复、提交或部署。回退仅移除本评审文件，不涉及业务与持久化数据。
