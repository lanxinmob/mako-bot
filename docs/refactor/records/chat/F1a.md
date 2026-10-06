# F1a 群状态与参与策略

## 开工

- 开工及规范重读时间：2026-09-14T11:52:34，Asia/Shanghai。
- 已读 AGENTS.md、docs/agent/{project,development}.md、docs/refactor/{plan,modules,status}.md、docs/group-participation.md 和 records/review/resumed/conclusion.md；src/test/docs 下未发现下级 AGENTS.md。
- 授权：用户明确要求继续 F1a 实际实现；R16 已附限制收口。Laplace 句柄 not_found 为用户提供的恢复背景，本次不声称恢复了它的执行结果。
- 核对：src/services/chat/group/、test/chat/group/、本记录均不存在，没有发现 F1a 部分产物。现有其他重构/B2/媒体改动保留。
- 唯一写入范围：src/services/chat/group/、test/chat/group/、docs/refactor/records/chat/F1a.md。
- 保留契约：原 GroupConversationService 构造参数、公共方法和数据类型；600 秒/60 条单调时钟窗口、群数量与负载上限、不可复用代次、单候选、沉默/称呼/引用/收尾、成功发送才开启延续。
- 方案：models 数据契约；window 有界状态与快照；policy 规则/等待/分类；candidates 生命周期；service 显式组合，不使用继承或动态转发。
- 验证：迁移原 test_group_conversation.py 的全部用例，补群隔离、旧任务取消与新候选交错；只运行群模块测试与结构/签名检查。
- 不修改 pipeline/config/plugins、原目录、共享状态文档；不读取 env，不启动真实服务、不提交。B2 由主 Agent、媒体由另 Agent 处理。
- 独立评审：本实现尚未独立评审，由主 Agent 安排；R16 结论不能当作 F1a 通过证据。

## 本地 PR 草案

将同级原草稿拆成显式组合的群状态包，供后续 F1c 接入。仅内存状态，重启清空；不接实际模型、传输或持久化。

## 结果

Maxwell 在写入六个源码模块及分组测试后因额度不足终止，未形成最终交付结论。
主 Agent 读取现场源码后运行 Python 3.10 群模块测试：57 passed（0.34 秒）。
该结果为主 Agent 实测，不能冒充实现 Agent 或独立评审结果；独立复审待完成。
