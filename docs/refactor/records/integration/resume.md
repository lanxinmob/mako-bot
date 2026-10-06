# R16 恢复与后续功能授权

2026-09-09 用户要求继续独立评审，并选择评审完成后优先开发群聊沉默、参与判断与防刷屏。
用户随后明确“现在有额度了可以运行”；因此恢复独立评审，未采用跳过评审的方案。

主 Agent 本次已重读 AGENTS.md、project.md、development.md、plan.md、modules.md、status.md。
保持 A 基线、源码隔离、无提交/部署/QQ 发送与隐私限制；评审过程中先不改受审源码。

## 本次职责

- Noether：R9–R11 聊天/自主行为接入、锁/批次/审批/发送时序；独立记录 resumed/core.md。
- Feynman：存储 P2 修复复查与 R6–R8 检索/工具/生成；独立记录 resumed/services.md。
- Boyle：Dashboard、其余服务路径、测试迁移和打包集成；独立记录 resumed/integration.md。
- 主 Agent：补 Python 3.10 实际运行验证，之后根据问题修复，再准备 F1 功能单元。

旧 Pascal、Dewey 的额度失败不视为通过；新评审以实际完成的报告为准。

## Python 3.10 环境

uv 已核对本机原有 Python 3.13.5/3.11.15，未发现 3.10。
Python 3.10.20 已安装到 ../.refactor-snapshots/python-runtimes，使用 --no-bin --no-registry，不改系统默认解释器。
隔离验证环境：../.refactor-snapshots/validation-py310；按项目 .[dev] 安装依赖，不替换原 .venv。
已确认 pytest 8.4.2、NoneBot 2.5.0、Pydantic 2.13.5、Redis 6.4.0、sentence-transformers 3.4.1。
compileall 与完整 pytest 已通过：Python 3.10.20，221 passed，119.87 秒。没有真实 QQ/付费 API 联调。

## 后续功能

本次只准备 docs/group-participation.md，未接入新功能。独立评审问题处置完成后实施 F1a–F1e。
小鸟、传送、期刊、提交或部署继续留在本轮范围之外。回退按原模块记录，不覆盖原 mako-bot 草稿。
