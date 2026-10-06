# H1 E1 恢复游标故障修复

2026-10-06 11:17 +08:00，恢复前重新读取AGENTS.md、project/development、plan/modules及status的当前批准与交接，复核B3 H1及entrypoint.md E1/E2、关联worker/discovery/recovery与专属测试。仅有根AGENTS，HEAD仍8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9；保留全部草稿。

McClintock综合句柄01a10c92-cfc0-7171-99ca-bd382e989ebf本次权威终态为workspace out of credits，delivery-synthesis.md未产出。不重启同一失败任务，也不把主Agent方案当独立综合结论；该关卡仍未完成。按已批准H1修复已确诊的故障不跳页要求，保留复核待办。

允许修改chat/history_delivery/worker.py、discovery.py，专属新故障测试、已有扫描测试中受内部调用接口影响的替身，以及说明。发送、模型、配置、Redis格式/TTL/租约和目标脚本不改。

主Agent实施方案：后台扫描显式开启raise_on_unavailable；worker在认领/收尾存储不可用时保留种类，完成本次预算内独立兄弟任务的尝试后向Scanner传播EffectUnavailable，不返回越过页的成功游标。即时consumer默认维持原字符串结果，坏证据在扫描模式标needs_review并可推进。目标写入未知但退避已确认属于已保存的retry_wait，仍可推进；结算返回False的CAS竞争也不冒充存储断连。取消继续透传，不释放活线程、不重发。

验证先以实际worker和隔离Redis复现claim/finish/defer边界的响应前/后丢失，接实际recovery函数正文确认游标保留、兄弟独立和其他恢复阶段仍推进；对照坏TTL/坏证据及已确认退避不永久卡页。只运行新增和受内部接口变更影响的扫描/即时入口节点，旧基础/全套不复跑。反向本补丁即可回退，但不删除任何永久证据；回退恢复旧游标缺口，并非推荐上线方案。

E2固化已完成：test_owner_interleavings.py人工sent/abandoned先于旧ACK EVAL获胜及读后新TTL拒绝，3通过（4.91秒）。E1修复前8项新增检查7失败1通过（14.02秒）：6个认领/finish/defer前后响应丢失均错误推进游标，坏TTL被折成unconfirmed；已确认退避可推进的对照通过。随后实施上述内部模式；修复后的受影响节点尚须核对。综合与修复独立确认仍待额度恢复，不能称完整H1通过。

修复后6个实际recovery/worker故障、坏TTL向下一合法动作推进、3项受调用签名影响的扫描检查及1项实际即时pipeline，共11通过（14.04秒）；已确认退避推进和原即时消费目标/结算丢响应契约2通过（2.99秒）。13个相关节点均有修复后通过证据，未复跑旧基础或全套。Python3.13定向compileall及git diff --check通过。

claim/finish/defer在响应前后断连时，实际recovery正文保留_history_cursor=17:0，另一个任务完成、原ACK时间与永久回执不变，其他恢复阶段游标仍推进。坏TTL保持原DUMP/TTL，报告needs_review并在下页处理合法动作；已确认退避保留retry_wait并可推进。False结算CAS竞争没有被推断成断连。两个调用入口默认兼容即时消费，扫描显式开启严格模式，测试替身同步新参数并断言True。

E1是主Agent修复和定向验证，E2是测试固化，不代替第三位独立综合/补丁确认。原effects/entrypoint报告仍绑定旧哈希；新worker/discovery分支需要独立确认，不改写原评审结论。未提交、部署或启动真实QQ/模型。

## 本次补丁证据

| 文件 | SHA256 |
| --- | --- |
| chat/history_delivery/worker.py | 89e63bb330d73bb5949912c1f95de48fa1b98108f2cf6d639944ee26297020bf |
| chat/history_delivery/discovery.py | a6d040d215de5bb05e96b39880a01541e0648cbb3954d5d838a8ff6906139e6b |
| test/chat/history_delivery/test_recovery_errors.py | 246a261faa6092624721dfc019eeb6a2a509339bea8bd6c50ac1b022c15cb18d |
| test/persistence/history_commit/test_owner_interleavings.py | f90d4e8f7e7ce90027a57a25f93649bb812c8dac3277410be954cc82f74057cb |

2026-10-06 11:23 +08:00结构扫描：471文件、452文本，0大文件、0拥挤目录；报告已刷新，Markdown摘要/JSON完整清单口径保持。后续独立复核需以此补丁与现有报告合并判断，不能把修复前反例报告改成通过。
