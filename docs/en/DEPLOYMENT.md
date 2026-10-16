# Deployment and Troubleshooting

[README](../../README_EN.md) · [Configuration](CONFIGURATION.md) · [中文](../DEPLOYMENT.md)

## Runtime Components

| Component | Role |
| --- | --- |
| Mako-Bot | Asynchronous Python application for QQ events, services, scheduled jobs and the Web dashboard |
| NapCatQQ | Separate QQ login process connected through OneBot V11 reverse WebSocket |
| Redis Stack | Application state and RediSearch vector indexes |
| Model/API services | Conversation generation, memory consolidation and information lookup, with credentials in private configuration |

For a local installation, follow the [quick start](../../README_EN.md#quick-start). Python requirements and dependencies are defined in [pyproject.toml](../../pyproject.toml).

The embedding model loads on demand through sentence-transformers. Its weights may download on the first vector operation. Memory use depends on the model, record volume, concurrency and image processing. There is no measured, universal minimum configuration. Protocol clients, models and services have their own licenses and terms.

## Prepare Configuration

Create `.env` from the [public template](../../.env.example), then enter your actual model endpoint, model name, API key and OneBot token. Preserve existing private configuration. Optional integer fields `GROUP_ID` and `AUTONOMY_OWNER_ID` cannot have empty values. Comment out or remove unused entries, or supply positive integers.

Set `PLUGIN_ENABLE_LIST` as shown in the README rather than relying on the current default loading list. See [plugins and tools](CONFIGURATION.md#plugins-and-tools) for details. Enable weather, autonomy and administration plugins only when needed, with their required credentials.

The application reads `.env` from the current working directory. Run local commands from the project root. Keep private configuration and logs out of version control.

## Docker Compose

The [Compose file](../../deploy/docker-compose.yml) includes the bot and Redis. Run NapCat separately. After configuring `.env`, run from the project root:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml up -d --build
docker compose --env-file .env -f deploy/docker-compose.yml ps
```

Compose sets the bot container's `HOST`, `PORT` and `REDIS_URL` to `0.0.0.0`, `8080` and `redis://redis:6379/0`, respectively. Redis and model configuration must be ready. The host port binds to `127.0.0.1:8080` by default and can be changed with `BOT_PORT`. The OneBot and Web ports inside the container remain 8080.

The author's current server has a total limit of **4 GB RAM / 2 CPUs**. This describes that deployment environment. Compose uses those values as the defaults for `BOT_MEMORY_LIMIT` and `BOT_CPU_LIMIT`, which set the bot container's resource quota. Adjust them for your host capacity and the resources used by NapCat, Redis and other processes.

Check readiness inside the container:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml exec mako-bot python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=5).read().decode())"
```

Docker's health check uses `/healthz` for process liveness. Use `/readyz` to check dependencies. Stop services with `docker compose --env-file .env -f deploy/docker-compose.yml down`. Avoid volume-removal options when retaining data.

## Connect NapCat

Enable OneBot V11 reverse WebSocket in NapCat and use the same token as the bot's `ONEBOT_ACCESS_TOKEN`.

| Topology | WebSocket address and requirements |
| --- | --- |
| Both processes run directly on the same host | `ws://127.0.0.1:8080/onebot/v11/ws` |
| NapCat on the host, bot in this Compose setup | Same address. Use the host port selected by `BOT_PORT` if changed |
| Both containers on the same Docker network | `ws://mako-bot:8080/onebot/v11/ws`. Join the NapCat container to the Compose network |
| Different hosts or Docker networks | Use an address reachable from NapCat and configure listening, forwarding, tokens and access scope |

Inside a container, `127.0.0.1` refers to that container. The default Compose host binding accepts only local connections. Another host cannot reach it directly, and another container cannot reach that loopback binding simply by using `host.docker.internal`. Share a Docker network or configure forwarding for your topology.

A reverse proxy must support WebSocket upgrades. Use TLS with `wss://` over untrusted networks. Do not put model keys or the Dashboard token in the WebSocket URL.

## Health Checks and Dashboard

| Endpoint | Meaning |
| --- | --- |
| `GET /healthz` | Returns `{"status":"ok"}` when the HTTP process responds |
| `GET /readyz` | Checks Redis connectivity and whether a model key is configured. Returns 503 on failure |
| `/mako/dashboard` | Public page shell. Reading its data requires authentication |
| `GET /mako/dashboard/api/summary` | Runtime summary authenticated by Bearer token or `X-Dashboard-Token` |

`/readyz` does not call the model API or validate embeddings, RediSearch or the QQ connection. `REDIS_REQUIRED` and `LLM_REQUIRED` affect these checks. Setting them to false does not remove the main chat workflow's persistence requirements.

Set `DASHBOARD_TOKEN` to at least 32 characters, then enter it in the dashboard. The frontend stores it in the current browser's localStorage, not the URL. An unconfigured summary API returns 503. Invalid credentials return 401. If the page opens without data, inspect authentication results.

## Persistence

The local quick-start Redis command uses a named volume and AOF. Compose also enables AOF and stores Redis data in `redis-data`, with application logs in `bot-logs`.

Compose currently has no persistent mounts for local memory images or the embedding cache. `ImageArchive` chooses its image directory relative to the running module. Source imports normally use `data/memory_images/` under the project. Check the actual path for an installed package. Add mounts for those paths if files must survive container recreation. Redis backups do not include local files.

When a send result is unknown, inspect state and logs before deciding what to do. Do not simply clear records or resend. After a restart, check application state, model-cost records and QQ delivery recovery separately.

## Startup and Connection Troubleshooting

Work through these checks in order:

1. **Configuration parsing fails:** check empty integer fields, Dashboard token length and the working directory used to read `.env`. Autonomy also requires an owner and targets.
2. **A plugin fails to load:** check its name in the bootstrap list and confirm that the module exists.
3. **HTTP responds but readiness fails:** check Redis configuration and connectivity, plus the DeepSeek/OpenAI key. Vector retrieval also requires RediSearch. A successful PING to ordinary Redis does not validate vectors.
4. **QQ is disconnected:** check the reverse WebSocket URL, token, port and container network. Confirm connection state on both NapCat and the application.
5. **Commands work but chat fails:** check model endpoint, name, API permissions, network and budget. `/help` does not call a paid model, so test model conversation separately.
6. **Images or memory fail:** check vision support, embedding downloads and vector-index dimensions. Changing the embedding model requires matching regenerated vectors and indexes.
7. **The dashboard has no data:** check summary API authentication, `DASHBOARD_TOKEN` and plugin loading.

Redact keys, user identifiers and chat content before sharing logs.
