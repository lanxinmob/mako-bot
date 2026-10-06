# 真实期刊查询与发现

2026-10-06 12:36 +08:00主Agent开始期刊实现前再次读取AGENTS、project/development、plan/modules及status当前批准，沿用12:20用户立即交付授权。允许写journals.py、journal_catalog.py、test_journals.py及本文，共享HTTP/命令接口保持；原草稿不改。没有下级AGENTS，无新Redis数据或费用配置。

契约：async journal/suggest(api, query='', *, user_id=0, now=None)返回DiscoveryReply。期刊查名称/校验ISSN，发表/投稿无参数按日发现真实刊物，主题查询展示近两年相关文章对应刊物和DOI；不生成评级、影响因子、费用或录用概率。

Crossref真实HTTP200确认期刊、单刊、刊内works和主题works端点。Nature查询首三项不是Nature，取30项可见完整Nature记录；因此必须检查精确名称或展示候选。PLOS One、Royal Society Open Science、BMC Bioinformatics、PLOS Computational Biology的ISSN/出版方本次已实际取回。

来源范围经官网核对：[PLOS One](https://journals.plos.org/plosone/s/journal-information)、[Scientific Reports](https://www.nature.com/srep/about/aims)、[IEEE Access](https://ieeeaccess.ieee.org/)、[Royal Society](https://royalsociety.org/journals/authors/which-journal/)、[BMC Bioinformatics](https://link.springer.com/journal/12859/aims-and-scope)、[PLOS Computational Biology](https://journals.plos.org/ploscompbiol/s/journal-information)。简介用简短中文概述，各卡链接官网和投稿说明，核对日期2026-10-06。

验证聚焦ISSN校验、同名歧义、近期日期/无未来论文、坏字段/无结果、按实际刊物归组、DOI链接/来源和源部分故障；Python3.10/3.13兼容，不调用收费模型。验证结果与独立综合另记。回退仅撤回本模块新增文件和调用接线，不修改真实数据。

## 实际完成情况

- journals.py与journal_catalog.py已实现；单刊展示刊名、ISSN、出版方、已有官网范围/投稿说明以及最多两篇近期论文，论文源失败仍保留已确认刊物身份。无精确名称时展示最多三个可查询候选，不认领首个模糊结果。
- 主题按最近两年取30条相关文章，剔除Front Cover/Contents等非论文条目、错误DOI/ISSN/日期，再列三个不同刊物的论文例证。日期精度保留，年月记录不伪造具体日；检索相关性不是投稿质量排序。
- 每日发现池6刊，按用户和北京时间日期稳定选择；已知刊名直接映射核对过的ISSN。使用跨年日期替换，仅闰日需回退至2月28日，普通月底日期完整保留。
- Python3.10期刊初始15项通过；新增日期检查后与其他发现功能及bootstrap整合：Python3.10与3.13各113项通过（2.31秒/2.80秒），其中期刊16项。测试禁用.env加载并拦截外部socket，HTTP均替身；不把113项当旧全项目验收。
- 真实公开检索1932-6203返回PLOS One及10.1371/journal.pone.0359973、10.1371/journal.pone.0358707；robot learning取到Robot Learning、Science Robotics、Discover Robotics的真实相关文章，过滤了IEEE Front Cover。没有按这些刊物的名气作质量认证。
- 独立综合及D1–D4补丁复核已完成，Arendt两版本各27项定向通过，附实群与媒体可达限制通过；报告见review.md，没有部署或真实QQ体验结论。
- Nature另有官网范围及初次投稿指引，不放进每日6刊池；官网正文访问触发idp重定向，范围依据本次官网检索摘要和Nature Portfolio官方介绍交叉核对：[官方刊物介绍](https://www.nature.com/nature-portfolio/about-journals/nature)、[初次投稿说明](https://www.nature.com/nature/for-authors/initial-submission)。实际近期Nature含新闻类型，卡片统一标注“近期文章”，明确Crossref不能区分研究/新闻，不能把journal-article自动视为研究论文。
