# Commands and Usage

[README](../../README_EN.md) · [Configuration](CONFIGURATION.md) · [中文](../COMMANDS.md)

## Conversation

The current character is Hitachi Mako from *Senren＊Banka*, defined in the [prompts](../../src/core/prompts.py). Changing characters requires editing prompts. There is no ready-made multiple-character configuration.

Send directly in private chat or @ the bot in a group. Blacklists, pacing, budgets and whether a reply still fits the topic affect admission. Character settings and memory provide context, but the model can still drift from the character.

Chat can use weather, web retrieval, notes and reminders. External services require credentials. Tool lists and user permissions also determine what can run.

## Birds, Historical Journeys and Journals

Enable `discoveries`. Send commands directly, after the bot's nickname or with an @ mention. Separate commands and arguments with spaces. These commands do not call paid models.

| Command | Behavior |
| --- | --- |
| `/help` | Help for discoveries and profile commands |
| `bird` | Random species and reusable image |
| `bird Passer montanus` | Species lookup by scientific name. Chinese species names are also supported |
| `journey` | Random historical background and fictional everyday story |
| `journey Tang dynasty` / `journey Egypt` | Filter by era or place |
| `journey again` | Draw another candidate |
| `journal Nature` | Look up a real journal by title |
| `journal 1932-6203` | Look up a journal by ISSN |
| `suggest` | Daily journal candidate |
| `suggest machine learning` | Find related journals through recent paper topics |

Chinese equivalents remain available: `小鸟` / `今日小鸟`, `传送`, `期刊`, and `发表` / `投稿`. The four English discovery command names are case-insensitive. Replies and historical stories remain mainly in Chinese.

Bird discovery selects reusable images from sources such as iNaturalist and preserves species, creator, source and license information. A limited offline catalog is used when online data is unavailable. Journeys distinguish sourced historical background from original fictional stories. Journal lookup supplies Crossref records and paper DOIs. Unverified rankings, impact factors and publication fees are omitted. Check the journal's website for scope and submission requirements.

Birds and journeys shuffle candidates per user, starting a new cycle after all are used. Restarting clears rotation state. A filter with only one candidate can repeat. Identical commands from the same person in the same session are ignored for three seconds. Different commands also share delivery queue limits. Unavailable reliable data is reported as unavailable.

Global and group/private tool lists and blacklists apply, with another permission check before sending. Tool names are `discoveries.bird`, `discoveries.journey`, `discoveries.journal` and `discoveries.help`. Include them when using an allowlist.

## Profiles and Personal Relationship Memories

| Command | Access and behavior |
| --- | --- |
| `人物档案` | Owner only. Shows profile count and the five most recently updated people |
| `人物档案 ID` / `人物档案 名称` | Owner only. Shows a complete profile. Duplicate names produce a list of IDs |
| `可塑性记忆` / `memory` | Legacy profile command, also owner only |
| `/memories` | Lists your entries, IDs, states and sources in your private chat, prioritizing active entries |
| `/explain-memory ID` | Shows source excerpts and timestamps. Explicitly identifies legacy entries without sources |
| `/correct-memory ID statement` | Corrects the same memory type and topic, creating a new ID and marking the previous entry replaced |
| `/forget-memory ID` | Clears same-topic ledger content and sources, removes exact mirrors and stops follow-ups. Historical chat remains |
| `/relearn-memory ID statement` | Explicitly authorizes recording a forgotten topic again. Creates a new entry without reactivating promises |
| `I used to like oolong tea, but I don't anymore` | Corrects a uniquely identified topic. Ambiguous matches require an ID |
| `Why do you think I like oolong tea?` | Explains the uniquely matching preference |
| `forget this` | Requires quoting a memory explanation sent to this user by this bot within five minutes |

Profiles require `precipitate_knowledge`, with the owner selected by `AUTONOMY_OWNER_ID`. Autonomy does not need to be enabled. Complete profiles are returned only in private messages, even when requested in a group. Personal relationship memories use `chat` and only operate on your own entries.

Chinese memory commands remain available: `关系记忆` / `我的记忆`, `解释记忆`, `纠正记忆`, `删除记忆` / `忘掉记忆`, and `重新记住`. Memory commands also accept input without `/`. Group usage only returns a generic instruction to use private chat.

Explicit preferences support Chinese and English, including `I like oolong tea` and `I don't like oolong tea anymore`. For example, use `/correct-memory ID I no longer like oolong tea`, then `/relearn-memory ID I like oolong tea` after forgetting. Topics match text, so `oolong tea` and `乌龙茶` are not automatically merged.

After the first correction or forgetting operation, related replies prioritize the ledger and suspend old profiles and vectors without sources. A pending storage result is not confirmation that forgetting succeeded.

## Reminders, Weather and News

| Command or message | Requirements |
| --- | --- |
| `/reminders` / `/我的提醒` / `/查看提醒` | `chat`. Lists your reminders in the current session |
| Natural-language creation, modification or cancellation in private chat or groups | Working `DEEPSEEK_*` configuration and session send permission. Private reminders go to their creator, group reminders to the original group |
| `/weather 上海` / `/天气 上海` | `weather`, `QWEATHER_HOST` and `QWEATHER_KEY` |
| `/news` / `/精选文章` / `/今日新闻` / `/日报` | `scheduler` and credentials required by the information service |

NoneBot-registered commands default to `/`. Use your configured prefix if changed. Discoveries and profiles parse commands separately and also accept the bare forms shown above.

For a first reminder, verify time and content with `/reminders`, then confirm actual delivery. See the [first-run walkthrough](FIRST_RUN.md#3-create-and-receive-a-reminder). Natural-language English input depends on the configured model.

## Exam Companion

Add `companion` to `PLUGIN_ENABLE_LIST`. Commands work only in your own private chat. Each person can have one active plan, with 1–3 tasks and one reminder. Explicit consent enables a post-exam review invitation. These commands do not call a model or infer consent from conversation. The parser currently uses **Chinese command names and field keys**. Keep the syntax below, replacing sample dates with valid future dates and ID with the creation receipt's ID. Commands can have a `/` prefix.

```text
创建考试计划 Math midterm | 考试=2026-10-20 09:00 | 提醒=2026-10-19 20:00 | 任务=Review chapter three；Complete a practice paper
我的考试计划
查看计划 ID
修改计划 ID 提醒=2026-10-19 21:00 | 任务=Review mistakes
同意回顾 ID 2026-10-20 20:00
撤销回顾 ID
提交回顾 ID 完成=1,2 | 感受=A little nervous | 下次=Review mistakes earlier
取消计划 ID
忘掉计划 ID
```

In order, these create, list, inspect and modify a plan, consent to or revoke a review invitation, submit a review, cancel a plan and forget a plan. Field keys mean exam (`考试`), reminder (`提醒`), tasks (`任务`), completed tasks (`完成`), feelings (`感受`) and next steps (`下次`).

All times use Asia/Shanghai. Exams must be within the next 90 days. A reminder must be at least five minutes after command receipt and at least five minutes before the exam. Review invitations must be after the exam, within seven days of it and at least five minutes after command receipt. Completed-task input accepts current task numbers or `无` (none).

`|` and `；` delimit fields and cannot appear inside content. Newlines are also rejected. Names allow 40 characters, each task 100, and feelings and next steps 200 each. Commands reject quoted messages, media, credentials and authorization on another person's behalf. If the invitation receives no answer, the bot does not pursue it. Plans close quietly seven days after the exam.

Queries show plan, consent, main-message delivery and bookkeeping states separately. Only explicit QQ acknowledgement produces sent. Unknown means a message may have been sent, so it is not automatically retried. Automatic review pauses while reminder delivery or bookkeeping is unconfirmed, but the user can still submit a review after the exam. Changing tasks or times revokes prior review consent, requiring fresh consent. A reminder already entering delivery cannot be changed by modifying the plan. Cancellation, revocation and forgetting stop actions that have not started. Started sends cannot be recalled. Actions outside their 30-minute execution windows are not sent late.

Exam plans are separate from relationship memories. Forgetting a plan clears its content, step content and exactly linked notes, with old material filtered under memory-control rules. Other relationship memories and personal notes remain, as do raw chat, sent messages, delivery audits and backups. The dashboard's exam-companion view is read-only and uses the same token. This feature requires confirmable Redis state and a single active bot process.

## Message History

Acknowledged plugin messages keep the latest 20 entries per bot and session for later reference, separately from ordinary chat history. `MAX_HISTORY_TURNS` controls ordinary history and defaults to 50 turns. Plugin history can temporarily remain in memory when Redis is unavailable, but unpersisted entries are lost on restart. Main-chat generation, history commits and recovery still require persistence.
