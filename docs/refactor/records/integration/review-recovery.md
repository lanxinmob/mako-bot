# R16 评审恢复与 CI 基线依赖

日期：2026-09-13；主 Agent 记录，不代替独立综合结论。

## 开工

本轮重新读取 AGENTS.md、project.md、development.md、plan.md、modules.md、status.md。
批准依据：A 基线 R0–R16，以及用户要求恢复独立评审后推进防刷屏。
HEAD 实测为 8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9。
允许路径：评审恢复记录、集成状态、CI 检出配置；不改业务行为。
保留契约：Dashboard 仍对照原固定基线；不跳过测试或放宽断言。

## 恢复证据

独立服务评审任务虽然最终额度错误，已有三条成功的 AST/运行探针命令。
原输出已通过 read_thread 重新核对并转录到 ../review/resumed/services-recovered.md。
core.md、integration.md 为其他独立评审者已完成的报告。
另派 Arendt 综合评审，任务 01a09990-95b4-7f53-9d64-92e49994ec75；其结论未返回前不宣称 R16 验收完成。

## CI 修正

test/dashboard/test_contracts.py 在常规 pytest 中调用 r5_contract.py。
后者通过 git show 读取固定基线提交的 Dashboard 实现。
CI checkout 原来未配置 fetch-depth；新提交的浅检出可能缺少历史对象。
为 checkout 设置 fetch-depth: 0，确保同一仓库的历史基线可读。
这是测试运行前提修正，不修改产品或测试期望；尚无远程 CI 执行证据。
回退仅移除本次 checkout 的 with/fetch-depth 配置，不动其他工作区改动。

## 后续修复输入

独立核心报告列出基线已有的重复批准、取消批次残留、发送后提交失败三类问题。
服务探针还显示临时文件写入失败时尚未追踪，后续无法清理。
这些行为修复归入后续功能工作，不声称已解决。
