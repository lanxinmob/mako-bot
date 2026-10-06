# discoveries 独立综合评审

最终结论：D1–D4 补丁独立定向复核通过，原 1 项 P1、2 项 P2、1 项 P3 全部关闭；本轮 discoveries 综合结论更新为附实群与媒体可达限制通过。下文保留初评版本及原始问题证据，最新补丁结论见末尾。未扩大旧链路或内容验证范围，不以本结论宣称真实 QQ 发送与媒体显示已验收。

## 授权、范围与版本

- 2026-10-06，本轮开工重读根 AGENTS.md、docs/agent/project.md、development.md、docs/refactor/plan.md、modules.md、status.md 当前批准与 docs/features/discoveries/implementation.md；12:44 +08:00 再核对当前接入及主 Agent 修正。目标路径未发现下级 AGENTS.md。
- 模块：本轮 discoveries；依据为 AGENTS 的两实现单元加独立评审安排及用户本次立即交付授权。本 Agent 为评审单元，没有参与历史、鸟类或主 Agent 的实现。
- 评审仅覆盖 src/features/discoveries/*、src/plugins/discoveries/__init__.py、src/core/bootstrap.py 新增插件名、test/features/discoveries/*、docs/features/discoveries/*、README 新增用法。
- 唯一写入为本文件。不改生产代码、不提交部署、不读取 .env、不调用付费 API 或真实 QQ，不运行历史全套测试，不重审旧费用/H1/G2/P6。
- 关联治理、发送及已安装 NoneBot/OneBot 源码只用于确认新入口调用契约；问题修复范围仍限本轮接入。
- 保留契约：明确命令、治理准入、旁听先行、通用聊天不得抢答、单条结构化图文、取消透传、公开请求有界、鸟种/授权一致、史实与虚构分离、真实刊物身份与文章证据。
- 三项接入复现对应插件 SHA256：31D3A23F196FB28BD855B48158F9877D37166FB79276B096FBFBEB62C0FD5A36。并行修改期间的结论对应此版本；后续补丁需定向复核。

## 初评问题与原始证据（已修复，复核见末尾）

### D1 / P1：全局工具白名单与禁用名单被新入口绕过

位置：src/plugins/discoveries/__init__.py:49–57；README.md:58–59；implementation.md 的“全局治理”交付表述。

入口只调用 GovernanceService.tool_allowed。该契约负责聊天黑名单、群/私聊工具名单与管理员限制；全局 TOOL_ENABLE_LIST/TOOL_DISABLE_LIST 原由工具准入单独检查。discoveries 没有执行这一层，因此仅调用 tool_allowed 不等于完整工具授权。

两版本真实 Bot.handle_event 分发均复现：

1. Settings(_env_file=None, REDIS_REQUIRED=False, LLM_REQUIRED=False, TOOL_DISABLE_LIST='discoveries.bird')。
2. 或 TOOL_ENABLE_LIST='search.web'，discoveries.bird 未获允许。
3. 合成普通成员发送“小鸟”；实际 discoveries service 替身被调用，真实发送调度进入 send_msg 替身并发送一条结果。

影响：显式全局禁用仍可请求公开来源和发送内容，白名单不能封闭新能力；文档所说禁用名单生效与实际不符。群/私聊、四个 discoveries 工具及 suggest→journal 映射都应遵守同一全局规则。

修复：在新入口发起查询前检查全局 enable/disable，禁用优先，再检查现有场景治理；复用现有纯 is_enabled 规则即可，无需改旧费用或执行器。

验收：覆盖全局禁用、非空白名单遗漏、全局允许但场景禁用，以及正常允许；拒绝时查询、发送和低优先级聊天均不执行。README 明确全局与场景名单均适用。

### D2 / P2：适配器去掉他人回复的 @ 后，命令被误认领

位置：src/plugins/discoveries/__init__.py:23–29；test/features/discoveries/test_plugin.py:34–44。

command_for 只检查 event.get_message()。真实 OneBot Bot.handle_event 先执行 _check_reply：对“回复他人 + @被回复者 + 小鸟”，成功读取被回复消息后会删除 reply 及对应 at。进入 matcher 时剩下“小鸟”，因此插件已经看不到原来的他人 @。

两版本真实适配器分发均复现：original_message 段为 ['reply','at','text']，被回复者 99、机器人 42；get_msg 仅用合成返回值。预处理后段为 ['text']、event.is_tome() 为 False，discoveries 仍发送图文并阻断 priority=40。单独“@99 小鸟”则正确拒绝。

影响：回复其他群成员并写命令词会触发机器人，违反本轮“拒绝发给其他账号的 @”契约。现有 Event 替身没有适配器预处理，不能检出这个问题。

修复：目标 @ 和夹带媒体边界以 original_message 为依据；命令正文可继续使用适配器规范化后的文本。不能简单要求 is_tome()，否则无 @ 的明确命令会失效。

验收：用真实 GroupMessageEvent→Bot.handle_event，加 get_msg/send_msg 替身，覆盖回复他人并 @ 他人、回复机器人、无 @ 明确命令、@机器人、夹带媒体；只有获准的命令进入发现服务。

### D3 / P2：查询与排队期间撤权后仍发送结果

位置：src/plugins/discoveries/__init__.py:49–54、63、71。

权限只在查询前核对。随后公开检索可能等待，command 发送也可能排队；finish_to_event 没有收到权限 guard，实际传输时不会复核黑名单。

两版本复现：真实 GovernanceService 配合合成存储起初允许用户 7；service.run 替身在返回前把该用户标记为黑名单；此时 tool_allowed 已返回 False，handler 仍通过真实 command 调度调用 send_msg 替身。

影响：请求等待期间管理员拉黑用户或群，已排队的新功能结果仍发出。此问题仅涉及 discoveries 新调用点，不要求重新验收旧发送可靠性。

修复：为新发送调用绑定最终权限 guard，在占用实际发送位置后再次核对；撤权需静默结束。注意共享 send_to_event 的 command 失败反馈会另发通知，因此不能只机械加 guard 而让撤权后又发“送达未确认”。新调用点须同时避免该未受授权的反馈，不修改旧发送协议。

验收：检索中撤权、等待发送位置时撤权均无结果和失败通知；权限未变仍仅发送一次。guard 自身失败时也不得放行。

### D4 / P3：发现帮助给出不受支持的敦煌筛选

位置：src/features/discoveries/service.py:15。

发现帮助提供“传送 唐朝／敦煌”，但当前八张卡片没有“敦煌”关键词，journey('敦煌') 返回未命中。当前纯函数已确认这一点。裸“再来”提示已由主 Agent 改为“传送 再来”，不再计入待修问题；首次组合探针在旧提示断言处失败，原因是磁盘已保存修正，不能把该断言当成最新缺陷证据。

修复：帮助筛选例子改为实际支持的地点。无需为帮助示例扩增史料或新增自然语言路由。

验收：从发现帮助复制筛选命令，均被 parser 认领并命中对应卡片。

## 定向验证与边界

- 本 Agent 独立运行命令2项、共享HTTP6项、插件3项、最新月底/闰日1项，共12项：Python 3.10.20 为12 passed / 1.23s，Python 3.13.5 为12 passed / 1.45s。
- 同两版本另用内存脚本运行真实 OneBot Bot.handle_event→NoneBot 依赖注入/rule/handler→共享 command 调度；仅加载 discoveries，priority=40 用记录替身，未加载通用聊天运行时或旧恢复任务。get_msg/send_msg 均为替身。
- 正常 @机器人命令仅一次 send_msg，消息段恰为 text/image，远程 '[CQ:at,qq=all]' 保持 text；通用 priority=40 不执行。场景禁用和普通成员调用管理员工具正确静默；这些成功项不能覆盖 D1–D3。
- 两版本另验证24请求上限、第25请求立即拒绝、排队/执行任务取消透传、_waiting归零、3个执行槽和host锁释放、取消不入失败缓存；响应流中途取消时 aclose 被调用，没有自动重试。
- 测试通过 stdin 临时脚本执行，python -B、pytest -p no:cacheprovider。Settings.model_config['env_file']=None；nonebot.init(_env_file=None)。清除业务环境变量，只保留Windows运行必需路径变量；网络请求均用MockTransport或API替身，socket仅允许asyncio自身socketpair建立所需连接。
- 初次评审隔离脚本清空SystemRoot导致WinError10106，随后过严的connect拦截阻止asyncio socketpair；均在测试准备阶段失败，修正隔离脚本后上述12项通过，未将准备错误归因于生产实现。
- 没有重跑历史22项或鸟类61项，也没有重跑主 Agent 的113项整合。其两版本通过和公开Crossref两查询成功属于实现方证据，已核对当前测试与交接文档，未冒充本 Agent 独立执行。
- README及bootstrap本轮变更的git diff --check通过；未做历史全仓测试或重新启动应用。

## 内容与外部来源核查

- 鸟类身份检查包含species/Aves、正整数ID、完整二名学名、已知名/ID相互绑定、歧义及实名失败不替换。图片路径ID、显式物种关联、作者、许可及可信HTTPS主机均检查。两个每日离线图各自绑定同一鸟种。
- 独立打开两个Commons文件页核对署名及许可：麻雀xulescu_g / CC BY-SA 2.0，欧亚鸲C-M / CC BY-SA 4.0；动态iNaturalist许可版本按官方LicenseModule核对。未发现需要改为其他鸟图或猜造许可的证据。
- 八张历史卡明确分列史实背景、虚构人物情节及虚构落点年份，没有编造寿命。独立浏览Yale、Met、Pompeii、UNESCO、V&A、NPS来源检查主要背景；故宫藏品页正文本次访问受限，使用故宫讲坛作交叉来源，不声称获取完整藏品说明。
- 最新journals.py已采用保留月底的两年窗口，publication earliest/latest为明确分支，DOI suffix经quote编码，ISSN有校验位，名称精确匹配否则列候选。文章日期精度保留，已知未来记录排除；主题检索仅认领相关文章对应刊物，不生成分区、录用概率或质量排名。
- 最新Nature仅加入NAMED_ONLY，没有进入每日六刊池；卡片已改“近期文章例证”并提示Crossref不区分研究/新闻，不再将d41586记录自动认作研究论文。完整“传送 再来”提示也已保存。这些已修正点不列为待修缺陷。主 Agent报告最新期刊两版本17项通过，本 Agent未重复该整组检查；对应样例/文档由主 Agent 同步更新。
- 当前主 Agent 样例中的1932-6203、robot learning及其他公开结果用于检查展示契约；本 Agent未重复相同公开HTTP smoke，也未把仅符合DOI语法的合成测试数据当成真实文献。

核对来源：[Commons麻雀](https://commons.wikimedia.org/wiki/File:Passer_montanus_(13955614566).jpg)、[Commons欧亚鸲](https://commons.wikimedia.org/wiki/File:Erithacus_rubecula_profile.jpg)、[iNaturalist官方许可实现](https://github.com/inaturalist/inaturalist/blob/main/app/models/shared/license_module.rb)、[Cornell鸟类资料](https://www.allaboutbirds.org/guide/Eurasian_Tree_Sparrow/overview)、[RSPB欧亚鸲](https://www.rspb.org.uk/birds-and-wildlife/robin)。

历史背景来源：[Yale食谱年代](https://news.yale.edu/2015/11/23/please-pass-hedgehog-pudding-holiday-recipes-yale-s-collections)、[Met埃及工匠村](https://www.metmuseum.org/essays/an-artisans-tomb-in-new-kingdom-egypt)、[Pompeii面包坊](https://pompeiisites.org/en/archaeological-site/bakery-of-popidio-prisco/)、[UNESCO长安廊道](https://whc.unesco.org/en/list/1442/)、[故宫讲坛](https://www.dpm.org.cn/forum_detail/99722.html)、[Met木版画协作](https://www.metmuseum.org/essays/woodblock-prints-in-the-ukiyo-e-style)、[V&A1851博览会](https://www.vam.ac.uk/articles/the-great-exhibition-of-1851)、[NPS金钉接轨](https://www.nps.gov/articles/goldenspike.htm)。

## 实群及媒体可达限制（不计入P1/P2/P3）

- 已核对图片物种、文件页许可及缩略图地址，但本机直连Commons媒体主机TLS超时已由实现方记录；本评审未下载媒体、未确认NapCat可达或实际QQ图文显示。需要在获准的部署环境独立验证，不能将返回image_url或MockTransport通过写成“QQ成功”。
- 本评审证明的是真实NoneBot代码在合成事件/适配器API替身下的行为，不证明实群交互自然度、真实平台ACK或消息在客户端最终显示。
- 固定站点、512KiB与10秒等上限适用于公开JSON元数据；QQ端根据远程图片URL下载的体积、耗时和平台行为没有由此获得同样保证。当前采用来源缩略图，但应保留该验收限制。
- 修复D1–D4后只需针对本报告复现及受改动影响的发现功能检查再验收，不以本报告要求进入旧费用/H1/G2/P6或重复历史全套测试。

## D1–D4 补丁独立复核（2026-10-06）

本轮 12:52 +08:00 开始核对最新补丁，再次读取根 AGENTS 及 project/development、plan/modules、status 当前授权和相关流程段落、implementation 当前修复记录。用户明确允许恢复 D1–D4 定向复核；唯一写集仍为本文件，原问题证据保留。目标路径没有下级 AGENTS。

复核仅检查最新插件、HELP/完整换站提示及 test_access.py、test_plugin.py、test_commands.py。不复跑 HTTP、历史、鸟类、期刊整组或旧费用/H1/G2/P6；未新增素材、修改生产代码或其他报告。

| 问题 | 最新修复位置 | 独立核对与结论 |
| --- | --- | --- |
| D1 / 原 P1 | src/plugins/discoveries/__init__.py:44–57、67、76 | permitted 使用现有 policy.is_enabled，先全局 enable/disable，再场景治理；suggest 映射 journal。四工具分别在群/私聊全局禁用时均无查询、发送或聊天回落；白名单遗漏、全局允许但场景禁用、正常允许均符合预期。关闭。 |
| D2 / 原 P2 | src/plugins/discoveries/__init__.py:27–34 | 目标 @ 和媒体检查改用 original_message，正文继续使用适配器规范化文本。真实回复预处理后 message 只剩 text，original_message 仍保留 reply/at；回复并 @ 他人不认领，回复机器人、普通明确命令、@机器人正常，夹带媒体拒绝。关闭。 |
| D3 / 原 P2 | src/plugins/discoveries/__init__.py:69–77、92–98 | 查询前及实际发送位置均执行 allowed；治理初始化经工作线程和 Lock。发送使用现有 send_to_group/private 的 command/guard 接口，避开 event 便捷接口的无守卫失败通知。两场景查询中撤权、真实 dispatcher 占位期间排队撤权、最终权限源抛异常均无结果、无通知、无聊天回落。关闭。 |
| D4 / 原 P3 | src/features/discoveries/service.py:15；src/features/discoveries/journeys.py:175、198 | 帮助使用真实支持的“传送 埃及”，保留“传送 唐朝”和完整“传送 再来”。复制这三个帮助示例均能解析并得到史实背景卡；未命中提示同样给完整换站命令。关闭。 |

本 Agent 独立执行：

- Python 3.10.20：access/plugin/commands **27 passed，1.44s**。
- Python 3.13.5：相同范围 **27 passed，1.67s**。
- test_access 的 Group/PrivateMessageEvent→Bot.handle_event→rule/handler→真实 OutboundDispatcher 路径保留；只替换公开查询、治理存储、OneBot API及低优先级聊天记录。排队撤权用实际占位发送回调制造等待，没有替换调度器为立即发送。
- 继续使用 stdin 安全脚本、python -B、pytest -p no:cacheprovider；Settings.model_config['env_file']=None、nonebot.init(_env_file=None)。清除业务环境变量，socket 仅允许 asyncio 自身 socketpair，不读取 env 文件、不访问公开 HTTP、收费 API、Redis 或真实 QQ。
- 两次执行前后分别核对插件、service.py、journeys.py 和三份定向测试的 SHA256，六个文件均未变化；两版本使用同一补丁内容。没有把主 Agent 的通过记录当作本次独立结果。

复核版本 SHA256：

- src/plugins/discoveries/__init__.py：93124810b48ea9413df0be230bdfee6d3785b0031574b227d326a405af7ce357。
- src/features/discoveries/service.py：137cefbaedd881cbfd641754dbc8d5b2d9d1ea51cdeba8af22bed8d25b145ce5。
- src/features/discoveries/journeys.py：6836c697f181c54cd283f390d36793e87f0b7e84d41e684cfe8d06615f19024e。

本次没有遗留 D1–D4 阻断项；原实群、Commons TLS/媒体可达、平台显示限制继续保留，旧可靠性评审状态不由本报告改变。
