# 部署与排障

[返回README](../README.md) · [配置](CONFIGURATION.md)

## 运行组件

| 组件 | 作用 |
| --- | --- |
| Mako-Bot | Python异步应用，处理QQ事件、业务服务、定时任务与Web面板 |
| NapCatQQ | 独立登录QQ，通过OneBot V11反向WebSocket接入 |
| Redis Stack | 保存业务状态，并通过RediSearch提供向量索引 |
| 模型/API服务 | 生成对话、整理记忆或查询资料，凭据放在私有配置中 |

本机部署见[README快速开始](../README.md#快速开始)，Python要求与依赖以
[pyproject.toml](../pyproject.toml)为准。

默认嵌入模型通过sentence-transformers延迟加载，首次使用向量功能可能下载模型权重。
内存需求取决于模型、记录量、并发和图片处理，仓库没有提供经实测的统一最低资源要求。
协议端、模型和服务各自的使用条件以其上游许可和服务条款为准。

## 准备配置

从[公开模板](../.env.example)生成 `.env`，填写实际模型地址、名称、API key和OneBot token。
已有私有配置时保留原文件。模板里的 `GROUP_ID=` 和 `AUTONOMY_OWNER_ID=` 不能以空值参与整数解析；
未使用时注释或删除，使用时填写正整数。

按README设置显式 `PLUGIN_ENABLE_LIST`，不要仅依赖当前默认加载清单；
原因和扩展方式见[插件与工具](CONFIGURATION.md#插件与工具)。
若需要天气、自主行动或管理命令，再选择对应插件和凭据。

应用配置相对当前工作目录读取 `.env`，本机命令应从项目根目录执行。
私有配置与日志不应进入版本控制。

## Docker Compose

当前[Compose文件](../deploy/docker-compose.yml)包含机器人和Redis，不包含NapCat。
在项目根目录、完成上述 `.env` 配置后运行：

```bash
docker compose --env-file .env -f deploy/docker-compose.yml up -d --build
docker compose --env-file .env -f deploy/docker-compose.yml ps
```

Compose将机器人容器内的 `HOST`、`PORT`、`REDIS_URL` 分别设为
`0.0.0.0`、`8080`、`redis://redis:6379/0`，并要求Redis与模型配置就绪。
主机端口默认仅绑定 `127.0.0.1:8080`；主机端口可以通过 `BOT_PORT` 调整，
容器内的OneBot和Web服务端口仍为8080。

作者当前部署服务器的总资源上限为 **4GB 内存 / 2 CPU**，这组数值用于说明作者的部署环境。
Compose 中 `BOT_MEMORY_LIMIT` 和 `BOT_CPU_LIMIT` 的默认值沿用这组数值，
控制机器人容器的资源配额。部署时应根据实际主机容量及 NapCat、Redis 等其他进程的占用调整配额。

检查容器内就绪状态：

```bash
docker compose --env-file .env -f deploy/docker-compose.yml exec mako-bot python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=5).read().decode())"
```

Docker自身的healthcheck使用 `/healthz`，只检查存活，不等于 `/readyz` 的依赖就绪检查。
停止服务使用 `docker compose --env-file .env -f deploy/docker-compose.yml down`。
需要保留数据时不要添加删除卷的选项。

## 连接NapCat

在NapCat中启用OneBot V11反向WebSocket连接，并设置与机器人
`ONEBOT_ACCESS_TOKEN` 相同的token。

| 拓扑 | WebSocket地址与要求 |
| --- | --- |
| 两者在同一主机直接运行 | `ws://127.0.0.1:8080/onebot/v11/ws` |
| NapCat在主机、机器人使用本文Compose | 同上；修改 `BOT_PORT` 后使用对应主机端口 |
| 两者在同一Docker网络 | `ws://mako-bot:8080/onebot/v11/ws`；NapCat容器需加入该Compose网络 |
| 分属不同主机或Docker网络 | 使用从NapCat可达的地址；配置监听/转发、token和访问范围后再连接 |

容器里的 `127.0.0.1` 指向该容器自己。
默认Compose主机端口只绑定回环地址，其他主机无法直接访问，另一容器也不能仅靠
`host.docker.internal` 访问这个回环绑定。可选择加入同一Docker网络，或按实际拓扑配置转发。

使用反向代理时需要支持WebSocket升级；跨不可信网络时使用带TLS的 `wss://`。
不把模型密钥或Dashboard token放进WebSocket URL。

## 健康检查与Dashboard

| 地址 | 含义 |
| --- | --- |
| `GET /healthz` | 返回 `{"status":"ok"}`，表示HTTP进程可响应 |
| `GET /readyz` | 检查Redis连通性及模型key是否已配置；失败时返回503 |
| `/mako/dashboard` | 公共页面外壳，数据接口另行鉴权 |
| `GET /mako/dashboard/api/summary` | 使用Bearer token或 `X-Dashboard-Token` 请求运行摘要 |

`/readyz` 不调用模型API、不验证嵌入模型或RediSearch能力，也不检查QQ是否已连接。
`REDIS_REQUIRED` 与 `LLM_REQUIRED` 会影响探针判定；将它们设为false不能使主聊天的持久化要求消失。

设置至少32字符的 `DASHBOARD_TOKEN` 后，在面板中输入相同token。
前端在当前浏览器的localStorage保存它，不通过URL传递。未配置时摘要API返回503，
凭据错误时返回401；页面能打开不代表数据已授权。

## 持久化

本机快速开始的Redis命令使用命名卷与AOF；Compose的Redis同样启用AOF并保存到
`redis-data` 卷，日志保存到 `bot-logs` 卷。

现有Compose没有为本地记忆图片或嵌入模型缓存配置持久化卷。
图片由 `ImageArchive` 根据运行模块位置确定保存目录；源码导入时通常在项目的
`data/memory_images/`，安装包运行时应核对实际路径。需要跨容器重建保留这些文件时，
按实际路径补充挂载。Redis备份不包含这些本地文件。

不要因为发送结果未知而清空记录或直接重发；先核对状态与日志，再处理未决项。
进程重启不等于应用状态、模型消费和QQ投递都已恢复完成。

## 启动与连接排查

按发生位置排查，不需要先修改所有配置：

1. **配置无法解析**：确认未使用的整数项没有留空，Dashboard token长度足够，
   自主行动开启时已填写owner和目标；确认从正确目录读取 `.env`。
2. **插件加载失败**：确认清单中每个名字都在bootstrap清单内且对应模块存在。
3. **HTTP可响应但未就绪**：检查Redis地址与连通性，以及DeepSeek/OpenAI key是否填写。
   向量检索还需要RediSearch，普通Redis的PING成功不足以证明向量功能可用。
4. **QQ没有连接**：检查反向WebSocket地址、token、端口和容器网络；
   在NapCat与应用两侧确认连接状态。
5. **命令可回复、对话失败**：核对实际模型地址、名称、API权限、网络和预算。
   `/help` 不调用付费模型，因此成功回复不证明模型配置正确。
6. **图片或记忆不可用**：核对模型是否支持视觉输入、嵌入模型下载和向量索引维度；
   修改嵌入模型后应重建匹配的索引与向量。
7. **面板没有数据**：区分页面访问与摘要API鉴权，核对 `DASHBOARD_TOKEN` 和插件启用情况。

提交问题前，对日志中的密钥、用户标识与聊天内容进行脱敏。
