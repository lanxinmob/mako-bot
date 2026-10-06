# 项目概览与模块说明

核对日期：2026-10-06，A 基线隔离重构工作区。以下区分当前实现、未完成工作和提案，不能把计划视为已上线能力。

## 项目概览

Mako-Bot 是以 NoneBot2 / OneBot V11 接入 QQ 的 Python 应用，包含聊天、工具、记忆、提醒、主动行为与 Owner 控制台。
NapCatQQ 是 README 描述的接入端；Python 依赖也包含 Lagrange 插件，实际启用以启动路径与配置为准。
聊天结果可调用模型与外部服务，Redis 保存历史、画像、提醒、治理信息等；代码也存在内存后备存储。
不要将后备内存描述为与 Redis 等价的持久化。

## 当前模块与文件结构

| 路径 | 职责 / 注意事项 |
| --- | --- |
| `bot.py`、`src/app.py` | 兼容入口与可安装入口；`mako-bot` 指向 `src.app:main` |
| `src/core/` | 配置、启动插件清单、日志、错误和系统提示词 |
| `src/models/schemas.py` | Pydantic 数据模型；变更可能影响持久化与接口 |
| `src/plugins/` | NoneBot matcher、定时任务、健康检查和 Dashboard 路由接入 |
| `src/plugins/discoveries/`、`src/features/discoveries/` | 明确命令接入和无收费模型的鸟类、历史传送、真实期刊查询；复用治理和command发送调度 |
| `src/services/persistence/` | 显式 facade、共享后端、按数据域分仓库；Redis 客户端在 backends/redis.py |
| `src/services/persistence/effects/` | P6幂等目标写入与版本绑定源完成回执；三类后台发送入口已接入，不能直接重放旧sent |
| `src/services/persistence/history_commit/` | H1原始快照、会话CAS/永久回执、冻结计划/送达状态、独立历史租约；基础已获两分项及综合附限制通过，新增消费者和人工核对待独立验收 |
| `src/services/chat/history_delivery/` | 普通主回复用发送前计划与ACK后两项消费，恢复每页10键/2任务，超过5分钟sending只标unknown；Owner查询/人工核对已接，未知时间两历史待核对；独立分项发现的E1游标故障已由主Agent修复、13项相关检查通过，综合/补丁独立确认因额度未完成，不重发或重调模型 |
| `src/services/persistence/generation/` | G1模型尝试身份、冻结费率日期、单次调用授权和独立费用租约存储；已接主回复/事实校验及Owner只读查询；修复扫描将超过5分钟的合法calling标unknown，保留原token晚结果，分类延迟取决于扫描进度 |
| `src/services/chat/generation/` | G1持久准入调用适配与幂等费用消费；G2每轮到期消费3项、另扫描10键修复可重建索引，SDK不自动重试；G1分项报告已完成，G2独立复审因额度中断 |
| `src/services/chat/` | 生成、消息、历史、事实检查、上下文与策略；pipeline/ 编排批次和发送提交 |
| `src/services/retrieval/` | 搜索客户端、规划、来源排序、验证和指标 |
| `src/services/tools/` | 意图、策略、执行器、媒体/文本/本地工具及临时文件 |
| `src/services/tools/media_cleanup/` | 有界进程内媒体资源回收，发送结束移交；失败保留句柄，关闭时有限收尾 |
| `src/services/autonomy/` | 模型、状态、策略、规划、审批和执行 |
| `src/services/memory/` | 关系、画像上下文、笔记、知识沉淀与向量存储 |
| `src/services/delivery/` | 提醒、发送去重与审计 |
| `src/services/delivery/state/` | Redis持久化发送状态、源版本校验、Owner核对与分页恢复；P4/P5独立复审及P6幂等补记待完成 |
| `src/services/delivery/effects/` | P6冻结计划、原子激活、独立补记租约与有界发现消费；三类后台发送器已切换，Owner可查询任务状态；旧sent无计划记录仅CAS标待核对，不重放；独立实现复审待完成 |
| `src/plugins/chat/recovery.py` | 单实例周期恢复未来提醒缓存及有效执行记录，另独立补记已sent任务；发送恢复保留开关和原bot/目标，不恢复unknown；补记不持有bot |
| `src/services/delivery/reminder_schedule.py`、`reminder_delivery.py` | 提醒先持久化再更新调度缓存、同版本发送与确认清理；启动仅恢复未来提醒 |
| `src/services/integrations/` | HTTP、模型、图片、语言、天气及地图适配 |
| `src/services/governance/`、`information/` | 治理权限/成本与新闻服务 |
| `src/utils/message.py` | QQ 消息规范化与媒体信息提取 |
| `src/web/dashboard/` | 控制台数据组装与接口 schema |
| `src/web/dashboard/static/` | 唯一前端源码/部署资源目录：HTML、原生 JS、CSS；没有 Node 构建链 |
| `test/` | 按 core/chat/persistence/delivery/autonomy 等领域分包；media/ 保存拆分后的媒体安全测试 |
| `eval/` | 搜索评估用例；不是已建立的完整评估流水线 |
| `scripts/` | 运维与结构检测脚本 |
| `deploy/`、`Dockerfile` | Compose、Redis Stack、应用容器 |
| `.github/workflows/ci.yml` | Python 3.10/3.13：编译、wheel 构建、pytest |
| `docs/agent/`、`docs/refactor/` | Agent 说明、方案与执行证据 |

当前扫描见 `docs/refactor/audit.md`；旧→新路径见 `docs/refactor/migration.md`。

## 总体运行流程

1. `src.app.bootstrap_application()` 配置日志、初始化 NoneBot、注册 OneBot V11。
2. `src.core.bootstrap` 根据插件清单加载应用插件；聊天和健康插件必选。
3. QQ 事件交给 matcher，完成规范化、治理检查和聊天/命令路由。
4. 聊天路径组合历史、上下文、工具与模型生成；持久化与消息发送涉及不同服务。
5. 调度任务处理提醒、资讯、关系跟进和主动行为。
6. Dashboard 启动钩子挂载静态资源与鉴权后的 summary API。

chat/autonomy 的同名包只在插件入口注册 matcher/job，服务接收显式依赖。
结构阶段保留 A 基线行为；随后 F1 已接入群旁听、参与准入、短期上下文、可取消候选和主回复发送调度。
这些功能仍在集成与独立评审中，其他发送入口尚未全部收口；没有实群自然度验收结论。
原 mako-bot 目录仍保存功能草稿，包括缺少 discoveries 插件的未完成接线；该缺口不属于本隔离工作区。

## 关键技术与规范

| 技术 | 已核对的依据 | 开发约束 |
| --- | --- | --- |
| Python | `>=3.10,<4.0`；CI 3.10/3.13 | 保留两端兼容 |
| NoneBot2、OneBot V11 | `pyproject.toml`、`src/app.py` | 注册点单一，防止搬文件导致重复 handler/job |
| Pydantic v2 / Settings | 配置与模型 | env 别名、默认值和校验均属于外部契约 |
| Redis / Redis Stack | 存储与部署配置 | key、TTL、索引、序列化、内存回退语义需保持 |
| asyncio、httpx、OpenAI 等 SDK | 服务实现 | 明确超时、取消、客户端生命周期和成本记录 |
| FastAPI | Dashboard 和健康路由 | 路由、鉴权和响应格式稳定 |
| 原生 HTML/JS/CSS | static README 与资源 | 保留唯一资源目录；不自行引入 React/Vite |
| pytest / pytest-asyncio | dev 依赖和现有测试 | 使用受控数据，不连接真实 QQ/收费 API |

尚未配置统一 Ruff、Black、mypy。test/dashboard/browser_contract.cjs 使用外部 Playwright/浏览器做受控比较，不属于生产依赖，也尚未接入 CI。
依赖版本以 `pyproject.toml` 为唯一维护入口；`requirements.txt` 只是安装当前项目的兼容入口。

## 前端 / 后端边界

- 前端：`/mako/dashboard` 是公开壳页面，不应含私人数据。JS 调用受保护的 `/mako/dashboard/api/summary`。
- 后端：`src/plugins/dashboard/__init__.py` 处理路由与 token 检查；`DashboardService` 负责数据组装。
- 当前支持 Bearer token 或 `X-Dashboard-Token`；前端目前把 token 放在 localStorage。重构需保持行为，若调整存储策略应单独评审。
- 安全响应头包含 CSP、no-store、no-referrer、nosniff；迁移资源不能放宽策略来绕过加载错误。
- `pyproject.toml` 打包 `src.web.dashboard/static/**/*`；移动模块须校验 wheel 中资源仍齐全。

## 后续业务功能与实群验收

- 群短期上下文：用户已接受 10 分钟 / 最多 60 条、仅内存暂存。
- 参与决策：允许沉默与等待、区分名字提及和真正调用、控制插话并丢弃过期候选。
- 工具与提醒：与可丢弃闲聊分开，发送与重试语义清晰。
- 2026-10-06小鸟、历史传送与真实期刊已在本工作区接入，Python3.10/3.13本轮各113项通过，公开服务实检有结果；见docs/features/discoveries/implementation.md。每日鸟图先有2种、历史8张、每日期刊6种；实名鸟类/刊名及主题查询走公开API。不推进旧费用增强，未部署或实群验收。
- 实群体验必须另有实际试用证据；单元测试不能证明自然度。

这些功能与行为保持的结构重构分别记录；旧可靠性独立复审仍是发布待办，不阻塞已获授权的新功能本地实现。
