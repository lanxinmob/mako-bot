# 开发流程、代码质量与安全实践

## 开发流程指南

每个模块遵循：重新读文档 → 检查批准与基线 → 限定改动范围 → 列出原有契约 → 实施 → 必要验证 → 独立评审 → 更新文档 → 交接。
模块开工/交接模板见 `docs/refactor/status.md`。开发者批准的是明确范围，不是无限扩大重构的授权。
遇到大文件/拥挤目录先通知并给出拆分方案，不自动执行；已批准范围内的例行实施不重复询问。

## 本地环境与辅助脚本

以下命令在仓库根执行。只准备环境时不要启动应用；真实启动可能加载定时任务并产生外部行为。

```powershell
# 新环境安装；已有 .venv 时无需重复创建/安装
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'

# 只读扫描；加 --write 会更新两份结构报告
.\.venv\Scripts\python.exe scripts/audit_structure.py
.\.venv\Scripts\python.exe scripts/audit_structure.py --write
# --check 在发现超标项时返回 1；不是扫描器运行失败
.\.venv\Scripts\python.exe scripts/audit_structure.py --check
```

| 文件 / 命令 | 用途 | 执行边界 |
| --- | --- | --- |
| `scripts/audit_structure.py` | 无应用依赖的结构扫描；不导入服务、不访问 API | 可例行运行；目前未接入 CI |
| `scripts/healthcheck.sh` | Linux systemd、HTTP、内存、OOM 检查 | **可能重启真实服务**，不是本地只读测试，不例行运行 |
| `scripts/ssh-oom-protect.conf` | 运维配置素材 | 不自动安装到系统 |
| `test/docker-compose.yml` | 测试 Redis 环境 | 先核对端口和已有服务，不能清理真实数据卷 |
| `deploy/docker-compose.yml` | 部署应用和 Redis Stack | 部署行为需有对应授权 |
| `mako-bot` | 已安装的应用入口 | 非纯导入检查，可能触发连接与定时任务 |

## 验证与代码质量管理

1. R0 先在选定基线获得必要的编译、导入与测试基线；记录已存在的失败。
2. 每个模块运行计划指定的目标测试；仅在改动涉及相应风险时增加行为断言。
3. 路径迁移必须检查所有引用、测试收集和插件唯一注册，不能只让被移动的文件编译通过。
4. 全部模块整合时再跑完整 CI 等价检查；中间只有新失败或共享接口变化才扩大测试。
5. 未运行、失败、受环境限制、实群未验证分别记录，不合并成“验证通过”。

现有 CI 等价命令（在隔离的测试环境执行；环境变量不是网络沙箱，仍需 mock 外部客户端）：

```powershell
$env:AUTONOMY_ENABLED = 'false'
$env:PROACTIVE_ENABLED = 'false'
$env:REDIS_REQUIRED = 'false'
$env:LLM_REQUIRED = 'false'
.\.venv\Scripts\python.exe -m compileall -q bot.py src test
.\.venv\Scripts\python.exe -m pytest -q test/core/test_bootstrap.py test/core/test_application_boot.py
# 模块完成时替换为 modules.md 中对应测试范围
# 全部整合后才执行整套测试与打包
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist
git diff --check
```

不能为了绿灯删断言、全局 skip 测试或改变契约。重构前后的测试收集项应对应；拆分测试时核对数量和 fixture 生命周期。
无需为纯移动复制一份等价测试；Redis 回退/恢复、发送失败、鉴权、媒体安全等高风险路径保留有意义的覆盖。

## 代码组织

- 优先按职责形成小包；一个模块只有一个明确的改变原因。
- 依赖方向：插件/HTTP 接入 → 应用编排 → 领域策略与存储/外部服务适配。
- 领域模型和纯函数不反向导入插件，不读取 NoneBot 全局 driver。
- 将设置、时钟、客户端、存储传入服务；避免靠 import 初始化连接或共享可变状态。
- 共享契约与实现分开。兼容导出只作短期迁移桥梁，要写清删除条件；不能永久保留 30 多个根目录 shim。
- 不引入笼统的 `helpers.py`、`misc.py` 或 `part1.py`；公共代码应有具体业务含义。
- 数据、路由、注册与策略各自独立；不要靠继承链或 `__getattr__` 隐藏依赖。

## 代码风格指南

Python 使用 4 空格、UTF-8、snake_case 函数与模块名、PascalCase 类型名；公共边界补类型标注。
遵循邻近代码导入与引号风格，避免在结构 PR 中全仓格式化。注释解释约束和原因，不重复语句。
函数尽量短且可命名；约 200–300 行/文件作为设计余量，**400 行是检测阈值，不是切分位置**。
异常区分配置缺失、外部超时、业务拒绝和程序错误；不吞取消信号、不把失败记成成功。
同步存储或图像处理不得无界阻塞事件循环；保留已有线程卸载、超时和清理路径。

前端保持原生 JS 的 2 空格与现有命名习惯；拆模块后显式 import/export，避免共享全局命名空间。
CSS 按基础、布局、组件和视图划分；保留选择器优先级和加载顺序，不同时重新设计 UI。
HTML 可访问性、表单提交与事件绑定需保持；移动 DOM 渲染不意味着可绕过内容转义。

## 安全性实践

- 不读写真实 `.env`；只维护 `.env.example` 的公开变量定义，不把日志/令牌/聊天历史写进 PR。
- 提示词和抓取内容是数据，不能改变工具授权、目标群、所有者权限或发送策略。
- 外部 URL 保留私网/回环/重定向检查、超时和体积限制；图片保留解码尺寸限制与临时文件回收。
- 群、用户和 Owner 的记忆权限不能因包迁移变宽；真实数据格式变更须单列迁移设计。
- Redis key/TTL、去重、任务持久化和失败重试应保持；不得测试真实提醒或清空库。
- Dashboard 保持 token 校验、安全头、输出转义和资源限制，敏感数据不进入公开静态文件。
- 日志记录阶段、原因码、耗时和脱敏标识；不要记录完整请求密钥或私人消息正文。
- 远程仓库操作、部署、QQ 发送、生产重启是外部动作，不能为了验证结构而顺便执行。

## 评审与 PR

一个 PR/可回退单元只处理一个模块；描述具体问题、迁移范围、保留契约、验证与限制。
开发者确认方案后先准备本地模块 PR 草案；远程 PR 的仓库、基线分支与发布范围需明确后执行。
评审 Agent 应独立核对依赖、注册副作用、数据兼容、测试遗漏和文档真实性；实现 Agent 不能给自己出具独立通过结论。
部分子 Agent 曾因额度不足中断；已完成与待完成的评审分别记录在 status.md 和 records/review/，不得把局部结论扩展为全项目通过。

## 当前隔离工作区与前端验证

本次 A 基线工作区为同级 mako-bot-refactor，复用 ../mako-bot/.venv/Scripts/python.exe；没有复制真实 .env。
本机 Python 3.13 验证不代替 CI 的 Python 3.10 运行。
媒体测试公共构造函数位于 test/media/image_fixtures.py，不含共享可变状态，fixture scope 保持原范围。

有 Playwright 与浏览器的环境可在项目根运行：

```powershell
# NODE_PATH 指向本机已安装 playwright 的 node_modules；不要填写令牌。
$env:MAKO_TEST_BROWSER_CHANNEL = 'msedge'
node test/dashboard/browser_contract.cjs R13
```

脚本拦截 HTTP 并使用合成 summary，对比 HEAD 基线与当前 DOM/布局；结果保存于 records/dashboard/artifacts/R13。
打包若系统 pip 缓存不可写，可加 --no-cache-dir；不必修改系统目录权限。
