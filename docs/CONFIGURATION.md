# 配置

[返回 README](../README.md) · [部署](DEPLOYMENT.md) · [命令](COMMANDS.md) · [English](en/CONFIGURATION.md)

应用通过 [Settings](../src/core/config.py) 读取环境变量和当前目录的 `.env`。可以先参考[公开模板](../.env.example)填写常用配置，默认值和校验规则以 Settings 为准。本页说明部署和使用中常见的配置，完整字段请查看源码。

## 最小配置

完成 README 中的模型、Redis 和 OneBot 连接配置后，填写以下插件清单：

```dotenv
PLUGIN_ENABLE_LIST=chat,health,discoveries,dashboard,scheduler,precipitate_knowledge
```

模板中的 `GROUP_ID` 和 `AUTONOMY_OWNER_ID` 是可选整数。不使用时请注释或删除对应行，使用时填写正整数。如果保留空值 `GROUP_ID=` 或 `AUTONOMY_OWNER_ID=`，Settings 会因为无法解析整数而报错。

仅首次部署时复制模板，不覆盖已有 `.env`。下面用到的 token、服务地址、模型名称和 key，请按实际部署填写，并将私有配置留在本地。

## 连接与持久化

| 字段 | 默认/要求 | 用途 |
| --- | --- | --- |
| `HOST` / `PORT` | `127.0.0.1` / `8080` | NoneBot HTTP 和 WebSocket 的监听地址与端口 |
| `ONEBOT_ACCESS_TOKEN` | 未配置 | 与 NapCat 使用相同的 token |
| `REDIS_URL` | 未配置时由 host/port/db 构建 | Redis 连接地址 |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` | `localhost` / `6379` / `0` | 未指定 URL 时使用的连接参数 |
| `REDIS_REQUIRED` / `LLM_REQUIRED` | `true` / `true` | 依赖就绪检查与相关接纳规则 |
| `REDIS_RETRY_SECONDS` | 30，至少 1 秒 | Redis 重试间隔 |
| `REDIS_HEALTH_CHECK_SECONDS` | 5，至少 1 秒 | Redis 健康检查间隔 |
| `LOG_FILE` | `logs/mako-bot.log` | 日志路径 |
| `LOG_ROTATION` / `LOG_RETENTION` | `10 MB` / `7 days` | 日志轮换与保留 |

部分 Repository 可以在 Redis 不可用时暂存到内存，但主聊天生成记录、历史发送计划和审批、恢复流程仍需要可确认的 Redis 状态。调整 `REDIS_REQUIRED` 只会改变相关检查，不能让应用脱离 Redis 完整运行。

## 模型与外部服务

| 字段 | 用途 |
| --- | --- |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | 主聊天的 DeepSeek/OpenAI 兼容接口配置，地址与模型按实际服务填写 |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | 未配置 DeepSeek key 时的聊天备用入口，也用于部分媒体工具 |
| `GEMINI_API_KEY` / `GEMINI_BASE_URL` | Gemini 图片相关能力，需同时配置相应工具 |
| `EMBEDDING_MODEL` | 默认 `moka-ai/m3e-base`，通过 sentence-transformers 加载 |
| `VECTOR_INDEX_NAME` / `VECTOR_PREFIX` | 向量索引名称与记录前缀 |
| `OLLAMA_API_KEY` | Ollama Web Search / Web Fetch |
| `OLLAMA_SEARCH_RESULT_COUNT` | 默认 5，允许 1—10 |
| `QWEATHER_HOST` / `QWEATHER_KEY` | 和风天气服务 |
| `TIANXIN_KEY` | 天行数据相关查询 |
| `AMAP_KEY` | 高德地图相关查询 |

主聊天优先使用 DeepSeek 配置，只有未填写其 key 时才选择 OpenAI 入口。 OpenAI 备用入口的模型目前在生成代码中指定，没有 `OPENAI_MODEL` 配置项。每日知识整理也使用 DeepSeek 配置，只填写 OpenAI key 不会启用同等的每日整理能力。

DeepSeek 配置中的模型名包含 `vision` 时，聊天会尝试把图片作为视觉输入。服务本身也需要支持对应的图片消息格式，单纯修改模型名不会增加视觉能力。 OpenAI 聊天入口也会尝试原生图片输入，每条消息最多 3 张。媒体工具的 `IMAGE_PROVIDER` 默认 `none`，它和主聊天的视觉能力使用不同开关。

更换嵌入模型后，需要重新生成匹配模型与维度的向量和索引。默认模型有非商用、研究用途限制，详见[上游模型说明](https://huggingface.co/moka-ai/m3e-base#-license)。

### 模型接入范围

下表说明当前代码为各项功能使用的接口和配置。目前还没有逐供应商、逐模型的真实部署兼容性报告，因此接入一个兼容接口后，仍需分别测试文字对话、图片、提醒解析和每日整理。

| 功能 | 当前入口 | 接口要求与限制 |
| --- | --- | --- |
| 主聊天 | 优先 `DEEPSEEK_*`，未配置其 key 时使用 `OPENAI_*`，备用模型固定为 `gpt-4o-mini` | 需要 Chat Completions 接口返回文字内容。请求失败后不会自动切换到备用入口 |
| 每日知识整理与人物档案更新 | `DEEPSEEK_*` | 根据文本或支持的图片输入返回摘要。只配置 OpenAI key 不会启用该整理流程 |
| 私聊与群聊提醒创建、修改与取消 | `DEEPSEEK_*` | 提醒解析需返回约定的 JSON，提醒发送回创建它的会话 |
| 主聊天原生图片输入 | DeepSeek 配置的模型名包含 `vision` 时启用，OpenAI 入口也会尝试 | 服务需要支持图片消息格式和视觉输入，每条最多 3 张。模型名符合约定不代表服务一定兼容 |

常规工具由应用自己的意图路由和执行器调度，主聊天请求不会发送原生 `tools` / function calling 参数。所以，供应商支持工具调用，并不代表提醒、资料检索和媒体功能都能直接使用。非原生图片描述和图片生成还需要各自的媒体配置，见[图片与 Dashboard](#图片与-dashboard)。

测试模型时，建议记录服务与模型名称、项目提交号、关键配置，以及各项测试的输入、输出和失败情况。真实 key 和私有地址请留在部署配置中，不要上传到测试材料里。

## 插件与工具

在 `PLUGIN_ENABLE_LIST` 中填写应用插件名，多个名称用逗号分隔。可用名称由 [bootstrap](../src/core/bootstrap.py) 定义，`chat` 和 `health` 始终保留。建议先使用 README 中的插件清单，再按需要添加：

| 插件 | 主要作用 |
| --- | --- |
| `chat` | 聊天、关系记忆与提醒命令 |
| `health` | 健康与就绪探针 |
| `discoveries` | 小鸟、历史传送、期刊与帮助 |
| `dashboard` | Web 面板与摘要 API |
| `scheduler` | 手动资讯等命令 |
| `precipitate_knowledge` | 每日知识整理与 owner 人物档案查询 |
| `weather` | 明确的天气命令 |
| `governance` | 管理命令 |
| `autonomy` | 自主行动运行入口 |
| `relationship_followups` | 关系跟进入口 |
| `companion` | 本人私聊考试计划、一次提醒与需本人同意的回顾，不受自主行动开关控制 |

留空时会加载完整应用插件清单。首次部署建议按 README 明确填写插件名，再逐步启用其他功能。添加插件时，也请确认加载清单中有该名称，并且对应模块确实存在。

应用入口按固定清单加载插件，没有调用 `nonebot.load_from_toml()`。安装了依赖，还需要在应用中启用对应插件。使用 NapCat 时，不需要另行启用 Lagrange 管理插件。

插件加载后，工具能否调用还要看权限配置。常用字段如下：

- `TOOL_ENABLE_LIST` / `TOOL_DISABLE_LIST`：全局允许/禁用名单。
- `GROUP_TOOL_ENABLE_LIST` / `GROUP_TOOL_DISABLE_LIST`：群聊工具范围。
- `PRIVATE_TOOL_ENABLE_LIST` / `PRIVATE_TOOL_DISABLE_LIST`：私聊工具范围。
- `ADMIN_ONLY_TOOL_LIST`：管理员工具，默认包含 `note.delete,note.update`。
- `TOOL_TIMEOUT_SECONDS`：默认 25 秒。
- `TOOL_MAX_CONCURRENCY`：默认 3。

小功能需要相应的 `discoveries.bird`、`discoveries.journey`、 `discoveries.journal`、`discoveries.help` 权限。如果设置了允许名单，请把需要的工具加入其中。工具执行前和消息发送前都会检查权限，已撤销的动作可能直接取消，不再发送提示。

## 记忆与数据记录

| 字段 | 默认与含义 |
| --- | --- |
| `RECORD_UNDIRECTED_GROUP_MESSAGES` | `true`，被动记录允许接入的群聊中未 @ 机器人的发言 |
| `GLOBAL_MEMORY_MAX_RECORDS` | 全局原始记录上限，默认 50,000，至少 1,000 |
| `MAX_HISTORY_TURNS` | 普通聊天历史容量，默认 50 轮，必须为正整数 |
| `AUTONOMY_OWNER_ID` | 默认未配置，填写正整数，指定能查询人物档案的 owner |

保存消息本身不会触发回复，黑名单中的用户和群也不会被记录。设置 `RECORD_UNDIRECTED_GROUP_MESSAGES=false` 停止被动群消息记录，进入聊天流程的消息仍可能保存。

每日整理任务默认在北京时间（Asia/Shanghai）22:00 处理过去 24 小时的记录，提炼重要事件并更新有发言用户的档案。这项功能需要启用 `precipitate_knowledge`，并配置可用的模型和存储。

群聊和私聊中的每条消息最多归档 3 张图片，记录中保留图片文件的引用。使用支持的视觉模型时，整理会把图片、发送者、群标识与文字上下文送入模型，下载失败的图片标为不可见。语音等未解析内容保存类型标记。本地图片不占普通聊天轮数。原始记录淘汰后，每日整理会根据仍保留的记录清理对应文件。

部署者应明确告知参与者记录范围，以及哪些消息和图片会送往模型服务。关闭被动记录不会自动删除已经保存的历史、画像或文件。人物档案查询结果只返回给 `AUTONOMY_OWNER_ID` 指定的 owner，在群里调用时也只通过私聊发送。设置 owner 不需要开启自主行动。

### 记忆范围与访问

在私聊中管理记忆，并不表示这些信息只会用于私聊。各类数据目前按以下方式保存和读取：

| 数据层 | 当前范围 |
| --- | --- |
| 近期聊天历史 | 按会话标识保存，群聊与私聊使用不同标识，群聊历史按群 ID 保存 |
| 本群近期消息窗口 | 观察到的群消息可作为后续回复的上下文。关闭被动持久记录后，这个窗口仍会保留，其内容也可能用于模型请求 |
| 人物档案与关系记忆 | 按 QQ 用户 ID 保存，同一用户在群聊和私聊中可能使用同一份档案与关系信息，昵称不用于区分身份 |
| 每日提炼的长期向量记忆 | 共享事件写入同一索引，检索没有按群或私聊范围进行结构化过滤。即使提示词保留了用户或群标识，也不能据此隔离访问权限 |
| 笔记与旧关系镜像 | 检索会按文本中的用户标识过滤部分私有笔记，并排除旧关系镜像，但没有实现全局记忆的完整会话隔离 |
| Web 面板 | 持有 `DASHBOARD_TOKEN` 即可读取实例汇总，包括人物、记忆和近期原始记录，没有按群成员分别设置查看权限 |

目前，私聊、不同群和人物档案之间没有完整的信息隔离。若参与者要求严格分开，请使用独立实例和存储。多人共享一个实例前，请先确认上述读取范围符合预期。人物档案命令仅限 owner 使用，但其他读取入口有各自的权限规则，面板则使用单独的 token。

生成回复时，会把人设、当前输入、选中的历史、档案和相关记忆发送到配置的模型服务。每日整理会处理保留的近期记录，其中可能包含发送者、群标识和可用的图片上下文。即使记录消息时没有回复，这些记录之后也可能用于整理或模型请求。

### 纠正与删除范围

`/关系记忆`、`解释记忆`、`/纠正记忆`、`忘掉记忆`（或 `/删除记忆`）只在本人私聊操作。更正只接受同类型、同主题的记忆，并会生成新 ID。遗忘会清空同主题账本的正文和来源片段，删除精确镜像并停止跟进。首次更正或遗忘后，相关回复会暂停使用旧整段画像、没有来源的向量和旧会话版本，日常整理也会过滤这些受控材料。遗忘控制和幂等摘要保存在 Redis 中，不会自动过期。普通聊天陈述不会解除控制，只有明确发送 `重新记住 ID 新陈述` 才能重新授权。

遗忘不会物理删除原始聊天、历史审计、owner 旧档案、向量备份或本地图片。旧档案会标为历史或暂停使用。存储或响应结果不明时，“待确认”还不能算成功。队列中的旧正文会取消，但已经开始发送的消息可能包含旧信息。这些控制目前只适用于单个活动机器人进程。多个活动进程需要另外设计协调机制。关闭被动记录也不会删除已有数据。

Web 面板当前提供查看，没有统一的“删除此用户全部数据”入口。如果需要清理其他存储层，部署者还需分别检查 Redis 记录、向量索引和本地文件。只删除原始消息，不会自动清除从中生成的所有记忆。

## 回复、预算与自主行动

| 字段 | 当前默认 |
| --- | --- |
| `CHAT_RHYTHM_ENABLED` | `true`，启用会话节奏控制 |
| `REPLY_RANDOM_CHANCE` | 0.001，范围 0—1 |
| `CHAT_REPLY_DEBOUNCE_SECONDS` | 1.2 秒 |
| `COST_CONTROL_ENABLED` | `true` |
| `DAILY_COST_LIMIT_GLOBAL` / `DAILY_COST_LIMIT_USER` | 3.0 / 0.3，应用内部成本限额 |
| `PROACTIVE_ENABLED` | `false` |
| `AUTONOMY_ENABLED` | `false` |

成本限额依据应用自己的统计和配置，实际费用请以供应商账单为准。已经发生的模型调用会单独记账，即使最终没有发送消息。费用状态无法确认时，可能需要等待补记或人工核对。

`ADMIN_USER_IDS`、`BLACKLIST_USER_IDS`、`BLACKLIST_GROUP_IDS` 均使用逗号分隔的 ID。开启自主行动时必须填写 `AUTONOMY_OWNER_ID`，并至少在 `AUTONOMY_GROUP_IDS` 或 `AUTONOMY_PRIVATE_USER_IDS` 中配置一类目标。实际运行还会检查白名单、风险、冷却时间和审批规则。

## 图片与 Dashboard

图片下载默认最多 10 MiB，宽高上限各为 4096，像素上限为 8,847,360。下载超时为 15 秒，图片调用频率限制为 30 秒。相关字段为  `IMAGE_MAX_DOWNLOAD_BYTES`、`IMAGE_MAX_WIDTH`、`IMAGE_MAX_HEIGHT`、 `IMAGE_MAX_PIXELS`、`IMAGE_DOWNLOAD_TIMEOUT`、`IMAGE_RATE_LIMIT_SECONDS`。

`DASHBOARD_TOKEN` 至少需要 32 个字符。未配置时，面板的数据 API 会返回 503。可以在本地生成一个：

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

将结果写入私有 `.env`，重启应用后在 Dashboard 中使用。 Web 页面本身不要求 token，读取运行数据时需要 Bearer token 或 `X-Dashboard-Token`。页面会把 token 保存在当前浏览器的 localStorage 中。
