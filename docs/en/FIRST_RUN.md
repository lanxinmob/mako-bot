# First-Run Experience

[README](../../README_EN.md) · [Configuration and privacy](CONFIGURATION.md) · [Commands](COMMANDS.md) · [Troubleshooting](DEPLOYMENT.md#startup-and-connection-troubleshooting) · [中文](../FIRST_RUN.md)

Complete the [quick start](../../README_EN.md#quick-start) and verify `/readyz`, `/help` and an ordinary greeting, then follow the steps below to try memory, group conversations and reminders.

## 1. Inspect, Correct and Forget a Memory

Send these messages in private chat:

```text
I like oolong tea
/memories
```

Look for `喜欢：oolong tea` and its memory ID. A chat reply alone does not confirm that memory was saved. This preference becomes a structured relationship memory without waiting for daily consolidation. If it is missing, check whether the message entered the chat workflow and whether storage is available. Command responses currently remain mainly in Chinese.

Replace `<memory-ID>` with the actual ID:

```text
/explain-memory <memory-ID>
/correct-memory <memory-ID> I no longer like oolong tea
/memories
```

The explanation should show the original source, `I like oolong tea`. Correction should create a new ID containing `不喜欢：oolong tea` and mark the old ID as replaced. Send `/forget-memory <original-memory-ID>` and check that all entries for that topic are forgotten with empty content. Repeating `I like oolong tea` must not restore it automatically. Explicitly send `/relearn-memory <original-memory-ID> I like oolong tea` to restore it.

After correction or forgetting, relevant replies stop using old profiles and vectors without sources. Raw chat, historical owner profiles and backups remain. Changing oolong tea to coffee is a different topic and must be recorded as a new fact. Topics match text rather than automatic translation, so `oolong tea` and `乌龙茶` are not merged.

### Recent History Versus Persistent Memory

To check whether a preference remains available after its source leaves recent history, set `MAX_HISTORY_TURNS=2` in a **test instance**, restart and follow these steps:

1. Send `I like oolong tea` and verify it with `/memories`.
2. Complete at least four ordinary chat turns unrelated to drinks. Command queries do not count as ordinary chat turns.
3. Ask `What would you recommend I drink?` and observe whether the reply uses the preference. The model chooses its wording and whether to use memory.
4. Check `/memories` again. Restarting alone does not clear persistent history and is not evidence that the source left context.

This checks structured relationship memory. Normal recent history defaults to 50 turns and does not need to be reduced for everyday use.

To test daily vector consolidation, enable `precipitate_knowledge`, configure `DEEPSEEK_*` and Redis Stack, record a recognizable fictional event in a test group and wait for the default consolidation job at 22:00 Asia/Shanghai. Verify the long-term record in the dashboard before asking about it after the source leaves recent history. To establish that a reply used vector retrieval, inspect retrieval hits and exclude other sources such as profiles. The answer alone cannot identify its source.

## 2. Observe a Group Conversation

In a test group, alternate ordinary conversation, an explicit @ mention of Mako and further conversation between several people. Leave time for replies. Observe when she responds, remains silent or follows a changed topic across a sequence of messages.

| Test input | What to observe |
| --- | --- |
| Several ordinary messages without @ mentions | Whether she responds to every message and whether the frequency suits the group |
| @ Mako with a clear question | Whether the request enters chat. Check permissions, budget and pacing if there is no reply |
| Several speakers or a topic change | Whether replies still address a current topic, with acceptable delay and frequency |

`CHAT_RHYTHM_ENABLED`, random reply probability and waiting times affect the result. Each run may differ. Disabling `RECORD_UNDIRECTED_GROUP_MESSAGES` changes passive saving, not the decision to reply to ordinary group conversation.

## 3. Create and Receive a Reminder

Reminder creation, modification and cancellation work in **private chats and groups**, using a configured `DEEPSEEK_*` service for parsing. Keep the bot online with permission to send to that session. Send directly in private chat, or @ Mako in the test group:

```text
Remind me to drink water in five minutes
```

Send `/reminders` in the same session and check the parsed content and time. Wait according to the machine's actual clock, confirm that the reminder arrives in that session, then inspect the list or deployment logs. Private reminders go to their creator. Group reminders return to the original group.

To modify it, try `Move the drink water reminder to ten minutes from now`. To cancel it, try `Cancel the drink water reminder`. Natural-language parsing depends on your model. Listing, modification and cancellation apply only to your own reminders in the current session. A conversational promise does not establish that a reminder exists, and a listed reminder does not establish delivery.

If an operation reports an unconfirmed result, inspect the list first. For unknown sends, follow the [persistence guidance](DEPLOYMENT.md#persistence). Dashboard autonomy tasks and chat reminders are separate records. Check reminders using their commands and actual delivery.

## Record Your Results

When reporting a problem or sharing a demonstration, include the project commit, model name, OS, deployment topology, relevant configuration and test time. For memory issues, include history capacity, consolidation status and the memory layer being tested. Mark time jumps when skipping waits in a video. Use synthetic or authorized records and hide QQ identifiers, avatars and credentials.
