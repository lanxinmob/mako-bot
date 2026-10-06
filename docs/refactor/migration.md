# 重构路径与接口迁移

A 基线：8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9；原 mako-bot 功能草稿未移入。
内部 Python 导入按下表迁移；mako-bot CLI、src.plugins.chat/autonomy 名称、QQ 命令和 Dashboard 路由保持。

## 大模块拆分

| 旧入口 | 当前实现 |
| --- | --- |
| services/storage.py | persistence/facade.py + backends/ + 数据域仓库 + autonomy/ |
| services/chat_context.py | retrieval/{models,context,planning,ranking,verification,formatting}.py + chat/context.py |
| services/chat_engine.py | chat/{models,engine,messages,history,facts}.py |
| services/tool_executor.py | tools/{models,executor,policy,media,text,local,temporary_files,dependencies}.py |
| plugins/chat.py 与 chat_delivery/chat_reminders | plugins/chat/ + services/chat/pipeline/；纯群文本渲染在 utils/rendering.py |
| plugins/autonomy.py | plugins/autonomy/ 接入 + services/autonomy/ 状态与工作流 |
| web/dashboard/service.py | service.py 聚合 + roadmap/ + presenters/ |
| dashboard.js | JS 入口 + js/{api,state,format,render,events}.js |
| dashboard.css | CSS 入口 + css/{base,layout,overview,cards,status,responsive}.css，原级联顺序 |

## 小服务移动

| 旧模块 | 当前模块 |
| --- | --- |
| `src.services.chat_policy` | `src.services.chat.policy` |
| `src.services.chat_rhythm` | `src.services.chat.rhythm` |
| `src.services.response_style` | `src.services.chat.response_style` |
| `src.services.search` | `src.services.retrieval.client` |
| `src.services.search_metrics` | `src.services.retrieval.metrics` |
| `src.services.affinity` | `src.services.memory.affinity` |
| `src.services.knowledge_precipitation` | `src.services.memory.knowledge_precipitation` |
| `src.services.mako_context` | `src.services.memory.mako_context` |
| `src.services.notes` | `src.services.memory.notes` |
| `src.services.relationship` | `src.services.memory.relationship` |
| `src.services.vector_store` | `src.services.memory.vector_store` |
| `src.services.http` | `src.services.integrations.http` |
| `src.services.llm` | `src.services.integrations.llm` |
| `src.services.gemini` | `src.services.integrations.gemini` |
| `src.services.image` | `src.services.integrations.image` |
| `src.services.language` | `src.services.integrations.language` |
| `src.services.emoji` | `src.services.integrations.emoji` |
| `src.services.amap` | `src.services.integrations.amap` |
| `src.services.weather` | `src.services.integrations.weather` |
| `src.services.chat_audit` | `src.services.delivery.audit` |
| `src.services.outbound_dedup` | `src.services.delivery.dedup` |
| `src.services.reminder` | `src.services.delivery.reminder` |
| `src.services.governance` | `src.services.governance.service` |
| `src.services.news` | `src.services.information.news` |
| `src.services.intent` | `src.services.tools.intent` |
| `src.services.redis` | `src.services.persistence.backends.redis` |

## 测试与依赖注入

- 详细测试映射：records/integration/test-mapping.json。媒体测试按语义分为六组，函数/类 AST 保持。
- StorageService 从 src.services.persistence 导入；共享内存在 persistence.backends.memory.memory_store。
- ChatEngine 从 chat.engine 导入，ChatRequest/ChatReply 从 chat.models 导入。
- SearchContextBuilder 从 retrieval.context 导入；搜索类型从 retrieval.models 导入。
- ToolExecutor 从 tools.executor 导入，ToolExecutionResult 从 tools.models 导入。
- 适配器测试使用 ToolDependencies/构造参数或 builder 的 dependencies；旧 shim 已删除，不再 patch 不存在的模块。
- Dashboard 比较脚本只在隔离子进程绑定历史模块名，以便加载 git show 基线；这不是生产兼容导出。
- 原配置、提示词、模型、Redis key/TTL/序列化未迁移；F1 恢复草稿时按本表逐项移植，禁止覆盖新包。
