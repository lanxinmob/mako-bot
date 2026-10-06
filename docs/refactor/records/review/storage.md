# R1–R3 独立评审

- 开工：2026-09-09（Asia/Shanghai）。本次已重新读取 AGENTS.md、docs/agent/project.md、development.md、docs/refactor/plan.md、modules.md、status.md；未发现 docs/src 下级 AGENTS.md。
- 批准：用户批准 A 基线 R0–R16，并明确本评审者只写 docs/refactor/records/review/**。
- 基线：HEAD 8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9；审查共享工作区未提交实现，不读取原项目草稿或 .env。
- 本地 PR 草案：独立核对 storage.py 到 persistence 的行为保持，重点共享状态、Redis override、归一化和显式 facade；此文档不是远程 PR。
- 保留契约：Redis key/TTL、序列化、内存回退、方法签名、旧导出和调用方注入语义。
- 验证计划：与 HEAD AST/代码比较，针对可疑差异运行受控离线探针；不重复整套 pytest。Python 使用新项目 cwd 下的 ../mako-bot/.venv/Scripts/python.exe，禁用字节码和 pytest 缓存写入。
- 独立性：本评审者未实现业务重构；实现者历史测试仅作为背景，不能代替本次验证。
- 当前状态：发现 1 项 P2 回归，待实现者处置；其余已检查路径未发现行为差异。
- 回退：只撤销本评审记录及本目录内的验证脚本；业务回退由实现者按各模块记录执行，不在本评审中操作。

## P2：显式注入 backend 前意外加载全局配置

位置：src/services/persistence/facade.py:34–35、backends/redis.py:9。
通过 object.__new__(StorageService) 构造、然后赋值 redis/settings 的既有适配器路径，
原实现不调用 get_settings；现在第一次 setter 经过 backend 属性，创建
StorageBackend(initialize=False)，仍立即执行 get_settings()。
因此显式提供 FakeRedis/自定义 settings 也依赖全局配置验证成功，并可能触发 .env 读取。
现有调用证据：test/test_storage_history_migration.py:23–25、34–35。
建议：在未初始化的注入路径延迟设置解析，确保赋值 redis/settings 不初始化全局配置。
没有读取真实 .env；通过令后端 get_settings 抛受控异常比较 HEAD 与当前，HEAD 完成读写，当前复现异常。

## 独立验证

在新项目 cwd 执行，均 exit 0；脚本明确把已复现回归作为报告输出，不表示该问题通过验收：

```powershell
& ..\mako-bot\.venv\Scripts\python.exe -B docs/refactor/records/review/compare_storage.py
& ..\mako-bot\.venv\Scripts\python.exe -B docs/refactor/records/review/probe_storage.py
```

- 69 个迁移方法 AST 等价，仅规范化 memory 路径和 normalization 函数定位；包括 key、TTL 和序列化表达式。
- 63 个 public facade 方法签名一致；每个方法的参数转发、仓库选择与 backend 身份独立核对通过。
- 两个正常构造的 facade 共享同一个默认 memory 对象；shim._memory 身份一致。
- Redis 自动刷新，以及显式 None/客户端 override 阻止 provider 再次调用，通过。
- 旧历史 key 迁移及裁剪、旧 trace/progress/profile 输入 HEAD/current 差分通过。
- Repository 内 self 调用均在对应仓库可解析；normalization 为纯函数。

验证限制：未连接真实 Redis、未测试重连竞态、未跑全套 pytest；未验证 Python 3.10 实际运行。
facade 上的内部方法 monkeypatch/子类覆盖不会自动传播到仓库；未发现当前生产调用依赖，暂列兼容风险而非第二项已证实产品缺陷。
所有脚本仅写本 review 目录；运行时禁止字节码、dotenv 读取及网络连接。未改业务、未提交、未部署。
