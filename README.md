# Mako-Bot

基于 `NoneBot2 + OneBot V11` 的拟人化 QQ Bot，支持自然对话触发工具、关系记忆、主动跟进和运行时治理。

## 快速启动

```bash
pip install -r requirements.txt
python bot.py
```
- 按场景启停能力：支持群聊/私聊工具白名单与黑名单。
- 权限控制：支持管理员用户与 admin-only 工具控制。
- 黑名单：支持静态配置黑名单 + 运行时命令黑名单。
- 成本约束：全局/用户日预算，工具调用与 LLM 调用按估算成本扣减。
- 并发模块化：工具按可并发类型并行执行，带超时与耗时日志。
- 关系记忆重构：事件/偏好/禁忌/承诺四类记忆写入存储与向量库。
- 主动对话引擎：定时扫描到期承诺，主动私聊回访。
- 人设防漂移：系统提示词加入硬约束与禁忌行为，回复后做风格清洗。

## 关键环境变量

- 基础：
- `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`
- `REDIS_URL`

- 工具治理：
- `TOOL_TIMEOUT_SECONDS=25`
- `TOOL_MAX_CONCURRENCY=3`
- `TOOL_ENABLE_LIST=`
- `TOOL_DISABLE_LIST=`
- `GROUP_TOOL_ENABLE_LIST=`
- `GROUP_TOOL_DISABLE_LIST=`
- `PRIVATE_TOOL_ENABLE_LIST=`
- `PRIVATE_TOOL_DISABLE_LIST=`
- `ADMIN_ONLY_TOOL_LIST=note.delete,note.update`

- 权限与黑名单：
- `ADMIN_USER_IDS=123456,234567`
- `BLACKLIST_USER_IDS=`
- `BLACKLIST_GROUP_IDS=`

- 成本控制：
- `COST_CONTROL_ENABLED=true`
- `DAILY_COST_LIMIT_GLOBAL=3.0`
- `DAILY_COST_LIMIT_USER=0.3`
- `LLM_COST_PER_1K_CHARS_INPUT=0.0015`
- `LLM_COST_PER_1K_CHARS_OUTPUT=0.002`
- `TOOL_COST_OVERRIDES=image.generate:0.12,search.web:0.03`

- 主动跟进：
- `PROACTIVE_ENABLED=true`
- `PROACTIVE_SCAN_MINUTES=20`
- `PROACTIVE_DEFAULT_HOURS=24`

## 管理命令

- `mako-admin block <uid>`: 拉黑用户
- `mako-admin unblock <uid>`: 解除拉黑
- `mako-admin cost`: 查看今日成本

## 目录说明

- `src/services/governance.py`: 场景权限、黑名单、成本治理
- `src/services/relationship.py`: 关系记忆抽取与回访任务
- `src/services/tool_executor.py`: 并发工具执行与治理接入
- `src/plugins/scheduler.py`: 日常任务 + 主动回访调度
- `src/plugins/governance.py`: 管理命令入口
