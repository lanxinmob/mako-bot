# G2b 到期费用消费

2026-09-30，依据已批准G2方案，范围为chat/generation/discovery.py、现有发现测试；保留原GenerationCostWorker的权威记录/租约/永久目标回执约束，不重调模型。

新增run_due：最多读取3个到期成员，每项先repair_current清理或同步发现状态，仅合法ID且repair返回repaired后调用原费用worker。无SCAN历史步骤，不依赖历史终态数量；异常成员只用invalid_member标签报告，不暴露任意字节。单项证据异常独立标needs_review，网络故障继续抛出，不冒称整轮成功。

初步两项隔离Redis验证通过（2.47秒）：禁止SCAN替身下坏队头可清理且真实费用正常完成；未知记录正文保持、不生成计费授权。后者进一步改为真实worker及键集合核验，验证结果补记如下。尚未接入定时任务，须与G2c修复扫描一并切换；独立评审受额度限制，未部署。

真实worker未知费用检查1项通过（1.59秒）：返回not_claimed，原文不变，仅移除到期索引键，没有新增费用计数器或回执。

## G2c恢复接线（2026-09-30）

新增repair_page，每次最多检查10个历史键，仅重建/清理索引，不执行费用worker；保留SCAN超量offset及空页后续游标。chat/recovery已切换为独立try运行run_due和repair_page，后者沿用_generation_cursor，消费失败不跳过修复。旧run_page暂保留内部兼容，不再由生产定时任务调用。
Python3.10新增修复及实际恢复适配器6项通过（2.96秒）：索引丢失可重建且不计费、12键分页不丢项、到期消费失败仍推进修复游标、其他恢复阶段异常隔离。未运行真实scheduler或QQ。尚需检查异常键编码的历史扫描、整体G2独立复审；此次接线不等于已部署。

## 异常键名边界续作

2026-09-30恢复时重读AGENTS、project、development、plan、modules、status；范围仅discovery及专属测试/交接文档，沿用批准G2，不改配置及权威证据格式。SCAN按命令关闭自动解码，再逐键surrogateescape解码供合法ID过滤，避免一个坏UTF-8键使整页失败；保留原始坏键。到期消费测试改为在实际execute_command边界禁止SCAN，修复测试加入真实Redis坏编码键并核对证据保留和不计费。

验证：Python3.10 discovery/index/store/cost_worker共30通过、1失败（38.69秒）。失败来自旧结算丢响应测试仍按单key的args[4]判断操作，G2双key后未注入故障；改为按numkeys定位ARGV操作，保留全部结算未确认/不重复计费断言。2026-10-05仅复跑该项，1通过（2.90秒），共31项各有通过证据，未重复全套。

Bernoulli（01a0f08f-eded-70a2-8c44-7218ad2f4a97）独立存储评审明确额度不足终止，未返回评审结论；消费分项及综合评审亦未完成。只读扫描427文件408文本，唯一超标为既存audit.md402行，0拥挤目录；未改其待批准格式。未部署、未调用真实模型/QQ。回退保留generation及费用receipt全部证据；可撤回索引消费者接线，但不得删除权威记录后重调模型。

## 2026-10-05 必需截止字段校验

本轮重读六份约束文档和G2批准方案；允许路径为generation/costs.py及现有test_index.py、本记录。主Agent发现decode_cost将缺失截止字段视为0，但索引Lua要求leased/retry_wait的对应截止时间存在，导致损坏队头持续返回index_unconfirmed并中断消费。两个隔离Redis复现均失败，证实问题。

修复统一解码校验：leased必须有cost_lease_until_ms，retry_wait必须有cost_next_attempt_at_ms；现有合法写入均已包含对应字段，未新增格式。损坏证据由现有CAS修复路径仅移除索引，不改正文、不推算时间、不计费。两个故障场景及正常pending/leased/retry/complete流转共3项通过（Python3.10，5.26秒）。未重复全套，独立复审仍未完成。

## 2026-10-05 五分钟未知分类（已批准）

重读规定文档后按新批准扩展索引修复Lua、API说明及现有索引测试。复用后台10键修复扫描，在合法记录、原始字节CAS及永久TTL校验之后，依据Redis TIME判断calling是否超过300000ms；只改state=unknown和cost_state=needs_review，不产生金额、不换token、不授权重调模型。晚到complete沿用原token仍可冻结结果；旧修复快照不能覆盖已完成状态。分类会随扫描访问发生，5分钟是最小年龄，不承诺第5分钟即时处理大历史库。

初步隔离Redis存储检查1项通过（2.74秒），随后增强为实际repair_page入口扫描，核对年轻记录不变、旧记录仅两字段变化、禁止重新start、无费用和索引、晚结果可完成及旧快照CAS拒绝。该增强结果另记；独立评审仍因额度中断。回退可移除分类分支，已unknown记录保持原证据和晚结果接口，不改回calling或重调模型。

增强后的实际扫描入口检查1项通过（Python3.10，3.09秒），git diff --check通过；未重复整套测试，未部署。
