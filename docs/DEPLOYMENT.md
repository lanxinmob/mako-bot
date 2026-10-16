# 部署与排障

[返回 README](../README.md) · [配置](CONFIGURATION.md) · [English](en/DEPLOYMENT.md)

## 运行组件

| 组件 | 作用 |
| --- | --- |
| Mako-Bot | Python 异步应用，处理 QQ 事件、业务服务、定时任务和 Web 面板 |
| NapCatQQ | 独立登录 QQ，通过 OneBot V11 反向 WebSocket 接入 |
| Redis Stack | 保存业务状态，并通过 RediSearch 提供向量索引 |
| 模型/API 服务 | 生成对话、整理记忆或查询资料，凭据放在私有配置中 |

本机部署可以按 [README 快速开始](../README.md#快速开始)操作，Python 版本要求和依赖以 [pyproject.toml](../pyproject.toml) 为准。

默认嵌入模型通过 sentence-transformers 按需加载，首次使用向量功能时可能需要下载模型权重。内存需求取决于模型、记录量、并发和图片处理，目前还没有经实测的统一最低配置。协议端、模型和服务各自的使用条件以其上游许可和服务条款为准。

## 准备配置

从[公开模板](../.env.example)创建 `.env`，填写实际使用的模型地址、名称、API key 和 OneBot token。如果已有私有配置，请保留原文件。模板里的 `GROUP_ID=` 和 `AUTONOMY_OWNER_ID=` 不能留空，不使用时请注释或删除对应行，使用时填写正整数。

请按 README 填写 `PLUGIN_ENABLE_LIST`，先使用已列出的插件，不要直接依赖当前默认加载清单。原因和添加插件的方法见[插件与工具](CONFIGURATION.md#插件与工具)。需要天气、自主行动或管理命令时，再启用对应插件并配置凭据。

应用会从当前工作目录读取 `.env`，所以本机命令需要在项目根目录执行。私有配置与日志不应进入版本控制。

## Docker Compose

当前 [Compose 文件](../deploy/docker-compose.yml)包含机器人和 Redis，NapCat 需要单独运行。完成上述 `.env` 配置后，在项目根目录运行：

```bash
docker compose --env-file .env -f deploy/docker-compose.yml up -d --build
docker compose --env-file .env -f deploy/docker-compose.yml ps
```

Compose 会将机器人容器内的 `HOST`、`PORT`、`REDIS_URL` 分别设为 `0.0.0.0`、`8080`、`redis://redis:6379/0`，并要求 Redis 和模型配置就绪。主机端口默认只绑定 `127.0.0.1:8080`，可以通过 `BOT_PORT` 调整。容器内的 OneBot 和 Web 服务端口仍为 8080。

作者当前部署服务器的总资源上限为 **4GB 内存 / 2 CPU**，这组数值用于说明作者的部署环境。 Compose 中 `BOT_MEMORY_LIMIT` 和 `BOT_CPU_LIMIT` 的默认值沿用这组数值，控制机器人容器的资源配额。部署时应根据实际主机容量及 NapCat、Redis 等其他进程的占用调整配额。

检查容器内就绪状态：

```bash
docker compose --env-file .env -f deploy/docker-compose.yml exec mako-bot python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=5).read().decode())"
```

Docker 自身的 healthcheck 使用 `/healthz`，检查的是进程存活。依赖是否就绪，需要查看 `/readyz`。停止服务时，使用 `docker compose --env-file .env -f deploy/docker-compose.yml down`。如果要保留数据，请不要添加删除卷的选项。

## 连接 NapCat

在 NapCat 中启用 OneBot V11 反向 WebSocket 连接，并使用与机器人 `ONEBOT_ACCESS_TOKEN` 相同的 token。

| 拓扑 | WebSocket 地址与要求 |
| --- | --- |
| 两者在同一主机直接运行 | `ws://127.0.0.1:8080/onebot/v11/ws` |
| NapCat 在主机，机器人使用本文 Compose | 地址同上。如果修改了 `BOT_PORT`，请使用对应的主机端口 |
| 两者在同一 Docker 网络 | 使用 `ws://mako-bot:8080/onebot/v11/ws`，NapCat 容器需要加入该 Compose 网络 |
| 分属不同主机或 Docker 网络 | 使用 NapCat 能访问的地址，并先配置好监听、转发、token 和访问范围 |

容器里的 `127.0.0.1` 指向该容器自己。默认 Compose 主机端口只绑定回环地址，其他主机无法直接访问。另一个容器也不能仅靠 `host.docker.internal` 访问这个回环绑定。可以让容器加入同一 Docker 网络，或按实际部署方式配置转发。

使用反向代理时，需要支持 WebSocket 升级。经过不可信网络时，请使用带 TLS 的 `wss://`。不要把模型密钥或 Dashboard token 放进 WebSocket URL。

## 健康检查与 Dashboard

| 地址 | 含义 |
| --- | --- |
| `GET /healthz` | 返回 `{"status":"ok"}`，表示 HTTP 进程可以响应 |
| `GET /readyz` | 检查 Redis 是否连通，以及模型 key 是否已配置，失败时返回 503 |
| `/mako/dashboard` | 页面可以直接打开，读取数据需要另行鉴权 |
| `GET /mako/dashboard/api/summary` | 使用 Bearer token 或 `X-Dashboard-Token` 请求运行摘要 |

`/readyz` 不会实际调用模型 API，也不验证嵌入模型、RediSearch 或 QQ 连接。 `REDIS_REQUIRED` 和 `LLM_REQUIRED` 会影响检查结果，但把它们设为 false 后，主聊天仍然需要持久化支持。

设置至少 32 个字符的 `DASHBOARD_TOKEN`，然后在面板中输入相同的 token。前端会把它保存在当前浏览器的 localStorage 中，不通过 URL 传递。未配置时，摘要 API 返回 503，凭据错误时返回 401。如果页面能打开但没有数据，请继续检查鉴权结果。

## 持久化

本机快速开始中的 Redis 命令使用命名卷和 AOF。Compose 中的 Redis 也启用了 AOF，数据保存到 `redis-data` 卷，应用日志保存到 `bot-logs` 卷。

现有 Compose 没有为本地记忆图片或嵌入模型缓存配置持久化卷。 `ImageArchive` 会根据运行模块的位置确定图片保存目录。直接从源码导入时，通常保存在项目的 `data/memory_images/`，通过安装包运行时请核对实际路径。如果希望重建容器后仍保留这些文件，需要按实际路径补充挂载。Redis 备份不包含这些本地文件。

发送结果未知时，先检查状态和日志，再决定如何处理，不要直接清空记录或重发。重启进程后，也需要分别确认应用状态、模型费用记录和 QQ 发送是否恢复。

## 启动与连接排查

可以按下面的顺序定位问题，不必一次修改所有配置：

1. **配置无法解析**：检查未使用的整数项是否留空，Dashboard token 是否足够长，并确认应用从正确目录读取了 `.env`。开启自主行动时，还要填写 owner 和目标。
2. **插件加载失败**：检查插件名是否在 bootstrap 清单中，以及对应模块是否存在。
3. **HTTP 可响应但未就绪**：检查 Redis 地址、连通性，以及是否填写 DeepSeek/OpenAI key。向量检索还需要 RediSearch，普通 Redis 的 PING 成功后仍要单独测试向量功能。
4. **QQ 没有连接**：检查反向 WebSocket 地址、token、端口和容器网络，并在 NapCat 和应用两侧确认连接状态。
5. **命令可回复、对话失败**：核对实际模型地址、名称、API 权限、网络和预算。 `/help` 不调用付费模型，收到它的回复后，还需要单独检查模型调用。
6. **图片或记忆不可用**：检查模型是否支持视觉输入，嵌入模型是否下载成功，以及向量索引维度是否匹配。修改嵌入模型后，需要重建匹配的索引和向量。
7. **面板没有数据**：检查摘要 API 的鉴权结果，再核对 `DASHBOARD_TOKEN` 和插件是否启用。

提交问题前，对日志中的密钥、用户标识与聊天内容进行脱敏。
