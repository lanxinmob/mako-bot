# R5 / R12–R15 与构建集成独立评审

## 开工与边界

- 日期：2026-09-09（Asia/Shanghai）；本轮文档重读已于 22:01:45 前完成。
- 基线：`8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9`；本轮 `git rev-parse HEAD` 与之一致，业务改动尚未提交。
- 已读：根 AGENTS.md、docs/agent/project.md、development.md、docs/refactor/plan.md、modules.md、status.md；仓库未找到更具体 AGENTS.md。
- 补读：integration 的 mapping.json、test-mapping.json、R15.md，Dashboard 验证脚本、相关源码、pyproject.toml、CI 和启动入口。
- 唯一允许写入：本文件；业务代码只读。不读真实 dotenv/私人数据，不运行应用、不发 QQ、不部署、不提交。
- 保留契约：Dashboard JSON/鉴权/安全头/资源路径/级联；R14 业务语义及导入注册边界；测试断言、参数化和 fixture 生命周期；wheel 资源和 CLI 声明。
- 不重复 chat/autonomy 核心与 persistence/tools/retrieval 算法评审；这些路径仅核对迁移引用、测试保留和打包集成。
- 主 Agent 正运行 Python 3.10.20 全套；本轮未重复整套，也不借用其通过声明作为独立结论。

## 结论与问题清单

本轮未发现 R5/R12–R15 与构建集成范围内可复现的新增功能回归或阻断项；无 P0/P1/P2 修复请求。
结论仅覆盖下述静态比较及实际运行探针，不代表整个重构验收，不代表群聊防刷屏已实现。
由于没有已确认缺陷，不虚构优先级、触发条件或修复建议；未覆盖事项列于末节。

## 独立核对与结果

### R5：Dashboard 数据、API 与模块边界

- 直接用 `git show <上述固定基线>:src/web/dashboard/service.py` 取得历史实现，未用主 Agent 保存的结果替代基线。
- 比较历史类方法和当前 service/presenters/roadmap 函数。归一化仅处理提取所需的 staticmethod 装饰器、self 参数以及 self./DashboardService. 调用前缀；所有提取方法均一致。
- 未提取的构造、取数、summary 聚合和 profile 查询方法 AST 一致；10 个路线图常量另由已检查脚本直接比较历史 AST/值。
- `src/plugins/dashboard/__init__.py` 和 `src/web/dashboard/schemas.py` 与基线逐行一致。
- 人工检查 service 到 presenter/任务函数的显式绑定与导入；未发现反向导入插件或新增读取全局配置。
- 读取并审查 r5_contract.py 后，本轮实际执行一次：empty/populated/legacy/complete × limit 1/200，共 8 组完整 JSON 和 storage.mock_calls 比较全部通过。
- 该探针固定时间、注入存储替身、拒绝 dotenv 和网络；同时检查真实 config/NoneBot 未导入，使用当前工作区模块。
- 实际执行 routes.py：公开壳、无/错误 token 的 401、未配置 token 的 503、Bearer/X-Dashboard-Token、limit 边界、JSON、安全头、所有嵌套 JS/CSS 的 HTTP 200 与 MIME 均通过。
- 路由探针使用真实 FastAPI 路由和 ASGITransport，但 settings、DashboardService 与 NoneBot driver 为受控替身。

### R12–R13：JS 提取、ES module、CSP 与 CSS

- HTML 相对基线仅增加 `type="module"`，仍通过同源 `/mako/dashboard/assets/dashboard.js` 加载。
- 独立遍历 JS 的静态相对 import，所有路径存在；入口 → events/render → state/format/api 的关系无循环初始化问题。
- 31 个函数移出 IIFE 后文本逐一一致，含规范化、转义用的 DOM 构造、各视图、过滤与百分比处理。
- 剩余 render/loadSummary 单独出具内存 diff 并人工检查：前者仅把五类交互转交 events，后者仅把 fetch/status/json 转交 requestSummary。
- 检查 events 保留 token.trim/localStorage 写入清除、active/query/status 更新、重新 render、loading/error/fallback/finally；api 保留 URL、Authorization 与错误文本。
- 检查入口先创建事件闭包，再赋值 renderer，再 render/loadSummary。创建闭包时不会执行尚未初始化的 render。
- CSP 仍是原同源策略，无新增 unsafe-inline 或外部依赖；实际路由探针覆盖模块 MIME 与安全头。
- 按 dashboard.css 的六条 @import 顺序读取 base/layout/overview/cards/status/responsive，去注释和空白后拼接内容与历史完整 CSS 严格相等；不存在规则重排。
- 没有新增前端构建链或第二套静态源目录。
- 读取 browser_contract.cjs，确认其比较固定基线、受控数据、DOM/布局及 CSP 差异；其会写其他产物，因此本轮不执行。status 中的浏览器通过记录属于既有证据，不冒充本轮实测。

### R14：小模块迁移及全仓导入副作用

- 独立读取映射中 26 个旧模块的 git show，与实际目标文件比较。
- 排除 Import/ImportFrom 节点后，103 个类/函数以及所有原模块级初始化语句 AST 一致；Redis 目标中新增 StorageBackend 单独排除，它属于 R1–R3 组合后端的集成，不在本评审重复评价其实现。
- 初次完整模块 AST 比较的差异逐项检查：部分 `from ... import a, b` 拆成两行、storage 改 persistence，以及 Redis 新增组合类；并非业务体变化。
- memory/integrations/delivery/governance/information 及 chat/retrieval/tools/autonomy 包入口没有新增注册代码；persistence 仅显式导出 StorageService。
- 检查七个其余插件（governance、health、precipitate_knowledge、relationship_followups、scheduler、vector_db、weather）的基线 diff：仅改服务导入，不增加 matcher/job 或构造调用。
- 全 src 的 288 处 `src.*` 绝对导入模块路径均可静态解析到当前文件/包；src/test/scripts/eval/bot.py 的旧服务路径搜索无命中。
- 扫描 services/web 未发现 `src.plugins` 反向导入、get_driver、on_message/on_command 或 scheduler 注册；已有 NoneBot logger/MessageSegment 依赖不能解读为完全无 NoneBot 依赖。
- R14 原有的 logger/SDK 导入、ZoneInfo 初始化和插件层实例构造仍存在；本结论是没有发现迁移新增副作用，不能说项目所有 import 都无副作用。
- bootstrap 插件清单、应用入口和 CLI 声明保持既有路径；未执行真实启动来验证可选插件环境。

### R15：测试迁移完整性

- 使用 git ls-tree 枚举基线测试，而非只相信迁移映射；逐一比较 28 个原测试文件和拆分前 test_image_safety.py。
- 基线 170 个 test_ 函数定义名称全部保留（按重数比较）；当前 196 个定义。这是静态定义数，不能与参数化后的 pytest 收集数混用。
- 按原类/函数比较 AST（保留装饰器、参数化、fixture，归一化导入路径）；媒体共享图片构造函数仍存在，fixture 未提升到根 conftest。
- 实际测试体差异逐项核对：application_boot/search_metrics 的 parents[1] → parents[2] 随目录深度调整；news_storage 的 `_memory` → `memory_store` 随后端迁移；媒体临时文件用例增强。
- 临时文件用例由自建 MinimalExecutor 和源码字符串检查，改为 TemporaryFiles/ToolExecutor 真正执行，断言产物、追踪列表、清理与失败路径；没有因迁移删除基线测试名。
- 其余原测试体在导入/patch 路径归一化后保持；旧模块式导入、字符串 patch 及搜索构建器来源变更已检查。
- R15 文档所说“媒体 AST 一致”是 R14→R15 阶段口径；相对指定 HEAD 的媒体临时文件测试确实增强，不能把整轮重构描述为所有测试 AST 原封不动。
- 本轮未做 pytest collect-only（避免重新导入整仓服务）或全套执行；211 项阶段收集和后续 221 项记录仍以对应阶段证据为准，等待主 Agent 当前全套结果。

### wheel / CLI / CI

- 直接读取现有 dist/mako_bot-0.1.0-py3-none-any.whl，无重建、无安装、无启动。
- 从当前 src 枚举 Python、静态目录文件和 mako.jpg，共 151 个期望文件；wheel 中全部存在，内容逐项一致（仅统一 CRLF/LF 比较）。
- wheel 的 console_scripts 实际为 `mako-bot = src.app:main`，与 pyproject.toml 和实际函数一致。
- setuptools 的 `src*` 包发现及 `src.web.dashboard = ["static/**/*"]` 覆盖新增子包、JS/CSS 嵌套目录；资源通过插件文件相对路径定位，不依赖 cwd。
- CI 仍有 Python 3.10/3.13、编译、wheel 构建、pytest；没有为迁移删去测试阶段。浏览器脚本目前未接入 CI。

## 实际执行与限制

- 本轮运行环境：复用 ../mako-bot/.venv/Scripts/python.exe，Python 3.13.5；探针使用 `-B`，不写 bytecode。
- 实际运行：多次无业务导入的内存 AST/源码/zipfile 探针，以及上述两个经检查的 Dashboard 离线脚本；没有运行整套 pytest、collect-only、pip wheel 或应用启动。
- 首个静态探针在读中文 JS 时因 Windows 默认 GBK 报错中止；改用 UTF-8 后重新完成后续 JS 路径和 wheel 核对。此前输出不是整条命令通过；重跑成功结果才用于结论。
- git 读取曾提示无法访问用户级 ignore 文件，但 git show/rev-parse/diff 成功；未修改系统配置。
- AST 路径解析不证明动态 import、可选依赖环境、运行时 import 顺序或所有插件唯一注册；chat/autonomy 的注册及发送时序由其他评审负责。
- 未独立复跑浏览器宽窄屏/焦点/布局，也未从安装后的 wheel 启动；资源内容与路径验证不能代替这些运行证据。
- 未验证真实 QQ、Redis、模型服务或实群自然度；不得用本报告作为防刷屏功能或部署验收。
- 本范围无待修复阻断项；最终集成需合并其他两位评审结论与主 Agent 的 Python 3.10 实际结果。若后续业务代码再变，本报告只适用于本次已读快照。
