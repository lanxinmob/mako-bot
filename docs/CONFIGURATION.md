# 配置

[返回README](../README.md) · [部署](DEPLOYMENT.md) · [命令](COMMANDS.md)

应用通过[Settings](../src/core/config.py)读取环境变量与当前目录的 `.env`。
[公开模板](../.env.example)提供常用字段，默认值与约束以Settings为准。
本页列出影响部署和使用的配置，不替代全部源码字段。

## 最小配置

完成README中的模型、Redis与OneBot连接配置后，使用显式插件清单：

```dotenv
PLUGIN_ENABLE_LIST=chat,health,discoveries,dashboard,scheduler,precipitate_knowledge
```

模板中的 `GROUP_ID` 和 `AUTONOMY_OWNER_ID` 是可选整数。
不使用时注释或删除对应行，使用时填写正整数；`GROUP_ID=` 或
`AUTONOMY_OWNER_ID=` 会触发当前Settings的整数解析错误。

仅首次部署时复制模板，不覆盖已有 `.env`。
下面涉及的真实token、服务地址、模型名称和key由部署者填写，不提交私有配置。

## 连接与持久化

| 字段 | 默认/要求 | 用途 |
| --- | --- | --- |
| `HOST` / `PORT` | `127.0.0.1` / `8080` | NoneBot HTTP与WebSocket监听 |
| `ONEBOT_ACCESS_TOKEN` | 未配置 | 与NapCat使用相同token |
| `REDIS_URL` | 未配置时由host/port/db构建 | Redis连接地址 |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` | `localhost` / `6379` / `0` | 未指定URL时的连接参数 |
| `REDIS_REQUIRED` / `LLM_REQUIRED` | `true` / `true` | 依赖就绪检查与相关接纳规则 |
| `REDIS_RETRY_SECONDS` | 30，至少1秒 | Redis重试间隔 |
| `REDIS_HEALTH_CHECK_SECONDS` | 5，至少1秒 | Redis健康检查间隔 |
| `LOG_FILE` | `logs/mako-bot.log` | 日志路径 |
| `LOG_ROTATION` / `LOG_RETENTION` | `10 MB` / `7 days` | 日志轮换与保留 |

部分Repository可以回退到内存。主聊天生成记录、历史发送计划以及审批/恢复流程需要
可确认的Redis状态；调整 `REDIS_REQUIRED` 只改变有关检查，不提供等价的无Redis运行方式。

## 模型与外部服务

| 字段 | 用途 |
| --- | --- |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | 主聊天使用的DeepSeek/OpenAI兼容接口配置位，地址与模型按实际服务填写 |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | 未配置DeepSeek key时的聊天备用入口及部分媒体工具 |
| `GEMINI_API_KEY` / `GEMINI_BASE_URL` | Gemini相关图片能力，需要相应工具配置 |
| `EMBEDDING_MODEL` | 默认 `moka-ai/m3e-base`，通过sentence-transformers加载 |
| `VECTOR_INDEX_NAME` / `VECTOR_PREFIX` | 向量索引名称与记录前缀 |
| `OLLAMA_API_KEY` | Ollama Web Search / Web Fetch |
| `OLLAMA_SEARCH_RESULT_COUNT` | 默认5，允许1—10 |
| `QWEATHER_HOST` / `QWEATHER_KEY` | 和风天气服务 |
| `TIANXIN_KEY` | 天行数据相关查询 |
| `AMAP_KEY` | 高德地图相关查询 |

主聊天优先使用DeepSeek配置位，未配置其key时才选择OpenAI入口；
OpenAI备用入口的模型当前由生成代码指定，没有 `OPENAI_MODEL` 配置项。
每日知识整理当前也使用DeepSeek配置位，仅配置OpenAI key不会启用同等的每日整理能力。

DeepSeek配置位的模型名包含 `vision` 时，聊天将图片作为视觉输入；
需要实际服务支持对应图片消息格式。模型名约定不能把文本模型变成视觉模型。
OpenAI聊天入口也会尝试原生图片输入；图片最多3张。
媒体工具的 `IMAGE_PROVIDER` 默认 `none`，与主聊天视觉能力是不同开关。

更换嵌入模型后，需要重新生成匹配模型与维度的向量和索引。
默认模型有非商用、研究用途限制，详见[第三方许可](THIRD_PARTY_NOTICES.md)。

### 模型接入范围

下表来自当前实现，说明各入口使用什么接口与配置。仓库尚无逐供应商、逐模型的真实部署兼容性报告，
因此不把代码存在或兼容接口名称标为“已验证支持”。换服务后分别核对文字、图片、提醒解析与每日整理。

| 功能 | 当前入口 | 接口要求与限制 |
| --- | --- | --- |
| 主聊天 | 优先 `DEEPSEEK_*`；未配置其 key 时使用 `OPENAI_*`，备用模型固定为 `gpt-4o-mini` | Chat Completions 接口能返回文字内容；备用入口不是请求失败后的自动切换 |
| 每日知识整理与人物档案更新 | `DEEPSEEK_*` | 根据文本或支持的图片输入返回摘要；只配置 OpenAI key 不会启用该整理流程 |
| 私聊与群聊提醒创建、修改与取消 | `DEEPSEEK_*` | 提醒解析需返回约定的 JSON；提醒发送回创建它的会话 |
| 主聊天原生图片输入 | DeepSeek 配置位的模型名包含 `vision` 时启用；OpenAI 入口也会尝试 | 服务必须接受图片消息格式并具备视觉能力；每条最多 3 张，名称约定不代表服务兼容 |

常规工具由应用的意图路由与执行器调度，主聊天调用没有发送原生 `tools` / function calling 参数。
不能仅凭供应商支持工具调用，就推断提醒、资料检索或媒体能力均已兼容。
非原生图片描述与图片生成还使用各自的媒体配置，见[图片与 Dashboard](#图片与dashboard)。

验证一个模型时应记录服务与模型名称、项目提交号、关键配置、每项实际输入输出及失败条件。
真实 key 和私有地址保留在部署配置中，不上传验证材料。

## 插件与工具

`PLUGIN_ENABLE_LIST` 是逗号分隔的应用插件名。当前名称由
[bootstrap](../src/core/bootstrap.py)定义，`chat` 与 `health` 始终保留。
推荐从README的显式清单开始，再按需要添加：

| 插件 | 主要作用 |
| --- | --- |
| `chat` | 聊天、关系记忆与提醒命令 |
| `health` | 健康与就绪探针 |
| `discoveries` | 小鸟、历史传送、期刊与帮助 |
| `dashboard` | Web面板与摘要API |
| `scheduler` | 手动资讯等命令 |
| `precipitate_knowledge` | 每日知识整理与owner人物档案查询 |
| `weather` | 明确的天气命令 |
| `governance` | 管理命令 |
| `autonomy` | 自主行动运行入口 |
| `relationship_followups` | 关系跟进入口 |
| `companion` | 本人私聊考试计划、一次提醒与需本人同意的回顾；独立于自主行动开关 |

留空时加载完整应用插件清单。首次部署建议使用README的显式清单，
再按需要启用其他能力；扩展时同时核对声明与实际文件。

应用入口按固定清单加载插件，没有调用 `nonebot.load_from_toml()`。
安装依赖不等于启用应用插件；使用NapCat时不需要另行启用Lagrange管理插件。

工具权限与插件加载是不同层。常用名单：

- `TOOL_ENABLE_LIST` / `TOOL_DISABLE_LIST`：全局允许/禁用名单。
- `GROUP_TOOL_ENABLE_LIST` / `GROUP_TOOL_DISABLE_LIST`：群聊工具范围。
- `PRIVATE_TOOL_ENABLE_LIST` / `PRIVATE_TOOL_DISABLE_LIST`：私聊工具范围。
- `ADMIN_ONLY_TOOL_LIST`：管理员工具，默认包含 `note.delete,note.update`。
- `TOOL_TIMEOUT_SECONDS`：默认25秒；`TOOL_MAX_CONCURRENCY`：默认3。

小功能需要相应的 `discoveries.bird`、`discoveries.journey`、
`discoveries.journal`、`discoveries.help` 权限。已有允许名单时需显式加入。
工具执行与发送前都会检查有关权限，已撤销的动作可能被静默取消。

## 记忆与数据记录

| 字段 | 默认与含义 |
| --- | --- |
| `RECORD_UNDIRECTED_GROUP_MESSAGES` | `true`，被动记录允许群聊中未@机器人的发言 |
| `GLOBAL_MEMORY_MAX_RECORDS` | 50,000，至少1,000；全局原始记录容量上限 |
| `MAX_HISTORY_TURNS` | 50，正整数；普通聊天历史容量 |
| `AUTONOMY_OWNER_ID` | 未配置；owner人物档案查询权限，填写正整数 |

消息记录本身不会触发回复，黑名单中的用户和群仍排除。
设置 `RECORD_UNDIRECTED_GROUP_MESSAGES=false` 停止被动群消息记录，
聊天流程接纳的消息仍可保存。

每日整理任务默认在Asia/Shanghai时区22:00处理过去24小时记录，提炼重要事件并更新有发言用户的档案。
需要启用 `precipitate_knowledge`、可用的模型配置与存储。

群聊和私聊中的图片每条最多归档3张；记录保留文件引用。
使用支持的视觉模型时，整理会把图片、发送者、群标识与文字上下文送入模型，
下载失败的图片标为不可见。语音等未解析内容保存类型标记。
本地图片不占普通聊天轮数；原始记录淘汰后，每日整理按保留记录清理对应文件。

部署者应明确告知参与者记录范围，以及哪些消息和图片会送往模型服务。
关闭被动记录不会自动删除已经保存的历史、画像或文件。
owner档案查询只向 `AUTONOMY_OWNER_ID` 返回，群里调用也只私聊发送；
设置owner不要求开启自主行动。

### 记忆范围与访问

“可以在私聊管理记忆”和“信息只用于私聊”是不同的范围。当前各层分别处理：

| 数据层 | 当前范围 |
| --- | --- |
| 近期聊天历史 | 按会话标识保存，群聊与私聊使用不同标识；群聊历史按群 ID 保存 |
| 本群近期消息窗口 | 观察到的群消息可作为后续回复的上下文；关闭被动持久记录不等于关闭这个窗口或阻止其内容用于模型请求 |
| 人物档案与关系记忆 | 以 QQ 用户 ID 保存，同一用户在群聊和私聊可被读取同一份档案与关系信息；昵称不是身份键 |
| 每日提炼的长期向量记忆 | 共享事件写入同一索引，检索没有按群或私聊范围的结构化过滤；提示词保留用户/群标识不等于权限隔离 |
| 笔记与旧关系镜像 | 检索结果会按文本中的用户标识过滤部分私有笔记，并排除旧关系镜像；这不提供全局记忆的完整会话隔离 |
| Web 面板 | 持有 `DASHBOARD_TOKEN` 可读取部署实例的汇总，包括人物、记忆和近期原始记录；没有按群成员分配的查看权限 |

因此，当前部署不应假定私聊、不同群与人物档案之间具有完整的信息隔离。
若参与者要求严格分离，应使用独立实例与存储；共享一个实例前先确认上述读取范围符合用途。
owner 人物档案命令的权限不等于所有读取入口都只对 owner 开放，面板 token 是另一项凭据。

回复生成会把人设、当前输入、选中的历史、档案和相关记忆发送到配置的模型服务；
每日整理会处理保留的近期记录，并包含发送者、群标识以及可用的图片上下文。
记录时不回复并不表示该记录不会参与后续整理或模型请求。

### 纠正与删除范围

`/关系记忆`、`解释记忆`、`/纠正记忆`、`忘掉记忆`（或 `/删除记忆`）只在本人私聊操作。
更正只接受同类型、同主题并生成新ID；遗忘清空同主题账本正文和来源片段，删除精确镜像并停止跟进。
首次更正或遗忘后，相关回复暂停使用旧整段画像、无来源向量和旧会话代次；日常整理也过滤受控材料。
遗忘控制与幂等摘要保存在Redis，不自动过期；普通陈述不能解除，须明确 `重新记住 ID 新陈述`。
这不物理删除原始聊天、历史审计、owner旧档案、向量备份或本地图片；旧档案标为历史/暂停。
存储或响应不明时不能把“待确认”当作成功；队列中的旧正文会取消，已开始发送的消息可能已经包含旧信息。
当前门闩保证限于单个活动机器人进程；多活动进程需要独立协调方案。
关闭被动记录同样不删除既有数据。

Web 面板当前提供查看，没有统一的“删除此用户全部数据”入口。
需要清理其他存储层时，由部署者分别核对 Redis 记录、向量索引与本地文件；
删除原始消息不能视为已撤回所有派生记忆。

## 回复、预算与自主行动

| 字段 | 当前默认 |
| --- | --- |
| `CHAT_RHYTHM_ENABLED` | `true`，启用会话节奏控制 |
| `REPLY_RANDOM_CHANCE` | 0.001，范围0—1 |
| `CHAT_REPLY_DEBOUNCE_SECONDS` | 1.2秒 |
| `COST_CONTROL_ENABLED` | `true` |
| `DAILY_COST_LIMIT_GLOBAL` / `DAILY_COST_LIMIT_USER` | 3.0 / 0.3，应用内部成本限额 |
| `PROACTIVE_ENABLED` | `false` |
| `AUTONOMY_ENABLED` | `false` |

成本限额使用应用的统计与配置，不替代供应商实际账单。
已发生的模型调用与最终消息是否发送分开记账，未知消费状态可能等待补记或人工核对。

`ADMIN_USER_IDS`、`BLACKLIST_USER_IDS`、`BLACKLIST_GROUP_IDS` 均使用逗号分隔的ID。
开启自主行动时必须填写 `AUTONOMY_OWNER_ID`，并至少配置
`AUTONOMY_GROUP_IDS` 或 `AUTONOMY_PRIVATE_USER_IDS` 中的一类目标；
运行还受白名单、风险、冷却与审批规则控制。

## 图片与Dashboard

图片下载默认最多10MiB，宽高上限各4096、像素上限8,847,360，
下载超时15秒、图片调用频率限制30秒。相关字段为
`IMAGE_MAX_DOWNLOAD_BYTES`、`IMAGE_MAX_WIDTH`、`IMAGE_MAX_HEIGHT`、
`IMAGE_MAX_PIXELS`、`IMAGE_DOWNLOAD_TIMEOUT`、`IMAGE_RATE_LIMIT_SECONDS`。

`DASHBOARD_TOKEN` 未配置时，面板的数据API返回503；填写时必须至少32字符。
可在本地生成：

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

将结果写入私有 `.env`，重启应用后在Dashboard中使用。
Web页面本身不要求token，运行数据需要Bearer token或 `X-Dashboard-Token`；
页面将token保存在当前浏览器的localStorage。
