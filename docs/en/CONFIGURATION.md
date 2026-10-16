# Configuration

[README](../../README_EN.md) · [Deployment](DEPLOYMENT.md) · [Commands](COMMANDS.md) · [中文](../CONFIGURATION.md)

[Settings](../../src/core/config.py) reads environment variables and `.env` in the current directory. Start with the [public template](../../.env.example). Settings is authoritative for defaults and validation. This guide covers common deployment and usage fields. Refer to the source for the full list.

## Minimal Configuration

After setting up model, Redis and OneBot connections from the README, set:

```dotenv
PLUGIN_ENABLE_LIST=chat,health,discoveries,dashboard,scheduler,precipitate_knowledge
```

`GROUP_ID` and `AUTONOMY_OWNER_ID` are optional positive integers. Comment out or remove unused entries. Empty assignments such as `GROUP_ID=` fail integer parsing.

Copy the template only for a new deployment. Preserve existing `.env` files. Use actual deployment tokens, endpoints, model names and keys, keeping private configuration local.

## Connections and Persistence

| Field | Default or requirement | Purpose |
| --- | --- | --- |
| `HOST` / `PORT` | `127.0.0.1` / `8080` | NoneBot HTTP and WebSocket listening address |
| `ONEBOT_ACCESS_TOKEN` | Unconfigured | Must match NapCat's token |
| `REDIS_URL` | Built from host/port/db when absent | Redis connection URL |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` | `localhost` / `6379` / `0` | Connection fields when no URL is supplied |
| `REDIS_REQUIRED` / `LLM_REQUIRED` | `true` / `true` | Dependency readiness checks and related admission rules |
| `REDIS_RETRY_SECONDS` | 30, minimum 1 second | Redis retry interval |
| `REDIS_HEALTH_CHECK_SECONDS` | 5, minimum 1 second | Redis health-check interval |
| `LOG_FILE` | `logs/mako-bot.log` | Log path |
| `LOG_ROTATION` / `LOG_RETENTION` | `10 MB` / `7 days` | Log rotation and retention |

Some repositories temporarily use memory when Redis is unavailable. Main-chat generation records, history delivery plans, approvals and recovery still require confirmable Redis state. Changing `REDIS_REQUIRED` changes checks, not those persistence requirements.

## Models and External Services

| Field | Purpose |
| --- | --- |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | DeepSeek/OpenAI-compatible main-chat configuration. Use the actual endpoint and model |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | Chat entry point when no DeepSeek key is configured, also used by some media tools |
| `GEMINI_API_KEY` / `GEMINI_BASE_URL` | Gemini image features, with corresponding tools configured |
| `EMBEDDING_MODEL` | Defaults to `moka-ai/m3e-base`, loaded through sentence-transformers |
| `VECTOR_INDEX_NAME` / `VECTOR_PREFIX` | Vector-index name and record prefix |
| `OLLAMA_API_KEY` | Ollama Web Search / Web Fetch |
| `OLLAMA_SEARCH_RESULT_COUNT` | Defaults to 5, range 1–10 |
| `QWEATHER_HOST` / `QWEATHER_KEY` | QWeather |
| `TIANXIN_KEY` | Tianxing data queries |
| `AMAP_KEY` | Amap queries |

Main chat selects DeepSeek configuration first and uses OpenAI only when the DeepSeek key is absent. The OpenAI fallback model is specified in generation code. There is no `OPENAI_MODEL` setting. Daily consolidation uses DeepSeek configuration too. Supplying only an OpenAI key does not enable equivalent daily consolidation.

When the DeepSeek-configured model name contains `vision`, chat attempts native image input. The provider must also support the image message format. Renaming a model does not add vision capability. The OpenAI chat entry point also attempts native image input, with at most three images per message. Media tools use a separate `IMAGE_PROVIDER` switch, defaulting to `none`.

Changing the embedding model requires regenerating vectors and indexes with matching model dimensions. The default model has non-commercial, research-use restrictions. See its [upstream license information](https://huggingface.co/moka-ai/m3e-base#-license).

### Model Integration Scope

There is no complete provider-by-provider or model-by-model deployment compatibility report. Test text chat, images, reminder parsing and daily consolidation separately after connecting a compatible API.

| Feature | Current entry point | Requirements and limits |
| --- | --- | --- |
| Main chat | `DEEPSEEK_*` first, otherwise `OPENAI_*` with fixed fallback model `gpt-4o-mini` | Chat Completions returning text. Failed requests do not automatically switch providers |
| Daily consolidation and profile updates | `DEEPSEEK_*` | Summaries from text or supported images. OpenAI-only configuration does not enable this workflow |
| Private/group reminder creation, modification and cancellation | `DEEPSEEK_*` | Required JSON schema from intent parsing. Delivery returns to the originating session |
| Native chat images | DeepSeek model name containing `vision`, or attempted by the OpenAI entry point | Compatible vision and image message format, at most three images per message. The naming convention alone does not prove compatibility |

Ordinary tools use the application's intent router and executor. Main-chat requests do not supply native `tools` or function-calling parameters. Provider support for function calling therefore does not establish that reminders, retrieval or media work. Non-native image descriptions and image generation require their own media configuration. See [images and dashboard](#images-and-dashboard).

When testing models, record provider/model name, project commit, relevant settings, inputs, outputs and failures. Keep actual keys and private endpoints in deployment configuration, out of shared test materials.

## Plugins and Tools

`PLUGIN_ENABLE_LIST` is a comma-separated list of application plugins defined by [bootstrap](../../src/core/bootstrap.py). `chat` and `health` are always retained. Start with the README list, adding features as needed:

| Plugin | Role |
| --- | --- |
| `chat` | Chat, relationship memories and reminder commands |
| `health` | Health and readiness probes |
| `discoveries` | Birds, journeys, journals and help |
| `dashboard` | Web dashboard and summary API |
| `scheduler` | Manual news and related commands |
| `precipitate_knowledge` | Daily consolidation and owner-only profile queries |
| `weather` | Explicit weather commands |
| `governance` | Administration commands |
| `autonomy` | Autonomy runtime |
| `relationship_followups` | Relationship follow-ups |
| `companion` | Self-owned private exam plans, one reminder and consent-based reviews, independent of the autonomy switch |

An empty list loads the full application plugin list. For a first deployment, explicitly use the README list and enable other features gradually. Confirm that every added plugin is in bootstrap and that its module exists.

The entry point uses a fixed loading list, not `nonebot.load_from_toml()`. Installing a dependency does not enable its plugin. NapCat deployments do not need the Lagrange management plugin enabled separately.

Tool permissions still apply after plugin loading:

- `TOOL_ENABLE_LIST` / `TOOL_DISABLE_LIST`: global allow/deny lists.
- `GROUP_TOOL_ENABLE_LIST` / `GROUP_TOOL_DISABLE_LIST`: group scope.
- `PRIVATE_TOOL_ENABLE_LIST` / `PRIVATE_TOOL_DISABLE_LIST`: private-chat scope.
- `ADMIN_ONLY_TOOL_LIST`: administrator-only tools, including `note.delete,note.update` by default.
- `TOOL_TIMEOUT_SECONDS`: 25 seconds by default.
- `TOOL_MAX_CONCURRENCY`: 3 by default.

Discoveries require `discoveries.bird`, `discoveries.journey`, `discoveries.journal` and `discoveries.help` as appropriate. Include needed tools in any allowlist. Permissions are checked before execution and sending. Revoked actions can be cancelled silently without an extra notice.

## Memory and Data Recording

| Field | Default and meaning |
| --- | --- |
| `RECORD_UNDIRECTED_GROUP_MESSAGES` | `true`, passively records messages without @ mentions in admitted groups |
| `GLOBAL_MEMORY_MAX_RECORDS` | Raw global record limit, default 50,000, minimum 1,000 |
| `MAX_HISTORY_TURNS` | Ordinary chat history, default 50 turns, positive integer |
| `AUTONOMY_OWNER_ID` | Unconfigured by default. Positive QQ user ID of the owner allowed to query profiles |

Recording does not itself trigger a reply. Blacklisted users and groups are not recorded. `RECORD_UNDIRECTED_GROUP_MESSAGES=false` stops passive group recording, but messages entering the chat workflow can still be saved.

Daily consolidation processes the previous 24 hours at 22:00 Asia/Shanghai by default, extracting significant events and updating profiles for people who spoke. It requires `precipitate_knowledge`, a working model and storage.

Each private or group message archives at most three images, with file references stored in records. With supported vision, consolidation sends images, sender/group identifiers and text context to the model. Failed downloads are marked unavailable. Unparsed content such as voice messages keeps a type marker. Local images do not consume ordinary chat turns. After raw-record eviction, daily consolidation cleans corresponding files according to retained records.

Tell participants what is recorded and which messages and images reach model services. Disabling passive recording does not delete existing history, profiles or files. Profile query results go only to `AUTONOMY_OWNER_ID`, through private messages even when requested in a group. Setting an owner does not require autonomy.

### Memory Scope and Access

Managing memory in private chat does not restrict its use to private conversations.

| Layer | Current scope |
| --- | --- |
| Recent history | Per session. Groups and private chats have distinct identifiers, with group history keyed by group ID |
| Recent group window | Observed messages can provide later context. Disabling passive persistence does not remove this window or prevent its use in model requests |
| Profiles and relationship memories | Per QQ user ID. The same person can share profile and relationship information across groups and private chats. Nicknames do not define identity |
| Daily long-term vectors | Shared events use one index without structured group/private scope filtering. User/group identifiers in prompts do not enforce access isolation |
| Notes and legacy relationship mirrors | Retrieval filters some private notes using textual user identifiers and excludes old mirrors, but complete session isolation is not implemented |
| Web dashboard | `DASHBOARD_TOKEN` grants access to instance summaries, including people, memories and recent raw records. There are no per-group-member view permissions |

There is no complete information isolation among private chats, groups and profiles. Use separate instances and storage for strict separation. Confirm these scopes with participants before sharing an instance. Profile commands are owner-only, other reading paths have their own permissions, and the dashboard uses a separate token.

Reply generation sends character prompts, current input, selected history, profiles and relevant memories to the configured model. Consolidation processes retained recent records, potentially including sender/group identifiers and image context. Recorded messages may reach later consolidation or model requests even if the bot never replied to them.

### Correction and Deletion Scope

`/memories`, `/explain-memory`, `/correct-memory` and `/forget-memory` operate only in your own private chat. Corrections accept the same memory type and topic and create a new ID. Forgetting clears same-topic ledger content and source excerpts, deletes exact mirrors and stops follow-ups. After the first correction or forgetting operation, related replies suspend old whole profiles, vectors without sources and old session versions. Daily consolidation filters controlled material too. Redis stores forgetting controls and idempotency summaries without automatic expiry. Ordinary statements cannot remove that control. Explicit `/relearn-memory ID statement` is required.

Forgetting does not physically delete raw chat, historical audits, old owner profiles, vector backups or local images. Old profiles become historical or suspended. Pending storage or response results are not success confirmations. Queued old content is cancelled, but messages whose sends have started may already contain it. These controls currently assume a single active bot process. Multiple active processes require additional coordination. Disabling passive recording does not delete existing data.

The dashboard is read-only and has no unified delete-all-user-data operation. Cleaning other layers requires separate inspection of Redis records, vector indexes and local files. Deleting raw messages does not automatically delete every derived memory.

## Replies, Budgets and Autonomy

| Field | Current default |
| --- | --- |
| `CHAT_RHYTHM_ENABLED` | `true`, session pacing |
| `REPLY_RANDOM_CHANCE` | 0.001, range 0–1 |
| `CHAT_REPLY_DEBOUNCE_SECONDS` | 1.2 seconds |
| `COST_CONTROL_ENABLED` | `true` |
| `DAILY_COST_LIMIT_GLOBAL` / `DAILY_COST_LIMIT_USER` | 3.0 / 0.3, application-level cost limits |
| `PROACTIVE_ENABLED` | `false` |
| `AUTONOMY_ENABLED` | `false` |

Limits use application statistics and settings. Provider invoices determine actual charges. Completed model calls are recorded even when no message is sent. Unconfirmed cost state may require bookkeeping recovery or manual reconciliation.

`ADMIN_USER_IDS`, `BLACKLIST_USER_IDS` and `BLACKLIST_GROUP_IDS` are comma-separated IDs. Enabling autonomy requires `AUTONOMY_OWNER_ID` and at least one target type in `AUTONOMY_GROUP_IDS` or `AUTONOMY_PRIVATE_USER_IDS`. Allowlists, risk, cooldown and approval rules also apply at runtime.

## Images and Dashboard

Image downloads default to 10 MiB, at most 4096 in either dimension and 8,847,360 pixels. Downloads time out after 15 seconds, with a 30-second image-call rate limit. Related fields are `IMAGE_MAX_DOWNLOAD_BYTES`, `IMAGE_MAX_WIDTH`, `IMAGE_MAX_HEIGHT`, `IMAGE_MAX_PIXELS`, `IMAGE_DOWNLOAD_TIMEOUT` and `IMAGE_RATE_LIMIT_SECONDS`.

`DASHBOARD_TOKEN` requires at least 32 characters. The data API returns 503 when unconfigured. Generate a token locally:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Store the result in private `.env`, restart, then enter it in the dashboard. The page shell does not require a token, but runtime data requires Bearer authentication or `X-Dashboard-Token`. The page stores the token in the current browser's localStorage.
