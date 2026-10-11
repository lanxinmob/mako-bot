# 群聊节奏回放样例

40 段合成片段，人物 A/B/C 与群/消息 ID 均为虚构。每类 3 段开发、2 段保留。
标签按交流意图编写，先冻结再测量；不根据运行输出改标签。
当前为评估 v2。原始 v1 保存为 cases-v1.jsonl；已见问题转入开发集，
冻结新的保留样例和全部指纹/替换记录见 frozen.json。
CLI 的 --split dev 用于定位；最后运行全量并单独报告保留集。

```text
python scripts/eval_group_rhythm.py --out <仓库外产物目录>
python scripts/eval_group_rhythm.py --out <仓库外产物目录> --compare <baseline/results.json>
```

## 数据格式

每行是一段独立的 JSON 场景，`schema_version=1`。主要字段如下：

| 字段 | 含义 |
| --- | --- |
| `case_id`、`category`、`split`、`hard` | 唯一场景 ID、场景类别、开发或保留集、是否属于硬场景 |
| `events`、`end_at_ms` | 按 `at_ms` 与 `seq` 排序的事件，以及观察截止时间；时间单位为毫秒 |
| `checkpoints` | 预期 `ignore/wait/reply`、回复对象、等待区间和发送次数 |
| `opportunities` | 应沉默、应回应或候选失效的观察窗口与允许发送次数 |
| `generation`、`transport` | 合成生成及发送依赖的延迟、阻塞和回执配置 |
| `rationale` | 标注依据 |

事件支持 `inbound`、`outbound_confirmed`、`release_generation` 和 `cancel_task`。
群、用户、消息 ID 为合成别名；引用必须指向同群已出现的消息，或明确标记未知引用。
完整字段约束见 [schema.py](../../src/services/chat/evaluation/schema.py)。

## 指标与结果

| 指标 | 分子 / 分母 |
| --- | --- |
| `forbid_reply`：误插话 | 应沉默窗口中发生聊天发送的窗口数 / 应沉默窗口数 |
| `require_reply`：漏回应 | 没有收到对应消息发送确认的有效回应窗口数 / 有效回应窗口数 |
| `invalidated_candidate`：过期回复 | 已失效候选仍被发送的窗口数 / 已失效候选窗口数 |

漏回应指标排除非正常发送、用户取消或需求被替换的窗口。
失效候选按原群、消息及候选序号匹配，避免把后续有效回复算作旧候选发送。
报告分别展示开发集、保留集及硬场景，另列重复发送数和逐例证据。

全量通过条件为：40 段全部完成、35 段硬场景全部通过且三个指标分子均为零，
总通过数至少 36，且没有重复发送。使用 `--compare` 时，数据指纹、参数、回放契约及
实现版本必须一致，三个指标分子不能增加。程序退出码 0 表示对应检查通过。

输出为 `results.json` 和 `report.md`；输出目录必须位于仓库外。
queue_until_ms 是排队故障夹具：以真实 dispatcher 的先行任务占据目标至指定时间。
deny_access / rhythm_cooldown 用于补充拒绝解释检查；均只影响合成依赖。
完整基线与比较报告放在产物目录；这些结果不证明生产 QQ 或模型理解表现。
