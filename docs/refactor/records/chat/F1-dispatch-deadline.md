# F1-D3 发送等待期限修复

2026-09-15 开工重读：AGENTS、project、development、plan、modules、status。
依据：F1 已授权范围及独立 F1-delivery.md 的 D3；主 Agent 接手已失效的修复任务。
允许路径：delivery/dispatcher.py、test_outbound_dispatch.py、本文与状态记录。

把持锁等待改为单事件循环内的发送占用状态与状态变更事件。
取得占用权前不 await；占用方独占 guard 与 send；等待者无需取得锁即可超时、取消并移除队列票据。
每次通知更换事件实例，等待者捕获对应事件，避免清除共享事件丢失唤醒。
零等待仅立即尝试，目标忙时直接拒绝；所有类别配额和优先级保持。
发送占用在 finally 释放；外部发送的合作式超时仍独立受 send_timeout 管理。
仅支持同一事件循环，不能扩展为跨线程/跨进程互斥或外部 exactly-once 保证。

必要验证：原调度测试及新增占用时超期、零等待、活动发送取消唤醒。
实际结果：Python 3.10 最终 11 passed（0.15 秒）。首轮发现 wait_for 在事件完成与取消同刻吞取消的交错，改用 asyncio.wait 并显式回收事件等待任务后通过；不隐去首轮失败。
独立复审待额度恢复，主 Agent 实施不算独立通过。
回退：仅反向本单元改动，保持已有业务状态和存储格式。
