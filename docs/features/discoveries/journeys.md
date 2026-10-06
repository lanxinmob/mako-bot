# 历史传送

## 开工证据

- 模块：F1 发现功能 / 串行实现单元 1：历史传送。
- 重读完成：2026-10-06 12:23 +08:00。本次逐项重读根 `AGENTS.md`、
  `docs/agent/project.md`、`docs/agent/development.md`、`docs/refactor/plan.md`、
  `docs/refactor/modules.md`、`docs/refactor/status.md` 当前批准记录及
  `docs/features/discoveries/implementation.md`；相关路径未发现下级 AGENTS。
- 批准依据：用户本次明确要求直接实施；2026-10-06 当前批准及 implementation
  记录优先完成小鸟、传送、真实期刊，旧费用增强和未完成评审不阻塞。
- 工作区：`D:/vscode workplace/fun/bot/mako-bot-refactor`；HEAD 为
  `8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9`。已有大量结构迁移和功能改动，
  保留原状；本单元开始时三个目标文件均不存在。
- 唯一写集：`src/features/discoveries/journeys.py`、
  `test/features/discoveries/test_journeys.py`、本文件。每文件少于 400 物理行，
  所在目录至多 10 个直属文件；共享 models、HTTP、插件及原目录仅供读取。
- 契约：同步 `journey(query: str = '', *, user_id: int = 0,
  now: datetime | None = None) -> DiscoveryReply`，共用现有模型；无 NoneBot、
  Redis、模型或运行时 HTTP 依赖。无参数每日按用户和北京时间日期稳定抽选，
  “再来”随机另抽；中文地区/时代过滤，未命中仅列已有选项。
- 内容边界：约八个时代/地区，包含中国；来源仅支持事实背景，人物情节明确
  标注原创虚构，公元前年份用正数显示，不编寿命。普通人的生活视角，正文
  约 400 汉字内，来源 URL 另计；没有核对图片时返回 `image_url=None`。
- 验证范围：必要的历史过滤、每日/时区选择及史实/虚构标签，Python 3.10 与
  3.13；只读结构检测与差异格式检查，不启动应用、不读 .env、不发 QQ、不提交。
- 实现者：本单元；独立综合评审由主 Agent 安排，本记录不冒充独立评审通过。

## 本地变更说明

实现已完成：八张原创人物生活卡片，每次只返回一张。事实背景和虚构人物、
情节分栏，故事年份也明确写为虚构落点；六个近似落点使用“约”，BCE 显示
“公元前1750年”等正数写法。没有年龄、寿命统计或真实人物冒名故事。

```python
from src.features.discoveries.journeys import journey

reply = journey("中国唐朝", user_id=123, now=None)
# 同步返回现有 DiscoveryReply；插件由主 Agent 接入。
```

无参数按 SHA-256(user_id、北京时间日期)稳定选择，避免 Python hash 在不同
进程变动；改变日期/用户可能得到相同卡片，不承诺逐日不重复。注入的无时区
datetime 按北京时间解释；有时区 datetime 先换算到 +08:00，与宿主时区无关。
筛选也按用户与日期稳定选择，地区和时代组合取交集，如“中国 唐代”、
“中国唐朝”、“英国 十九世纪”；每个词须由已有关键词覆盖，不能把“中国火星”
当成“中国”。未命中只列目录内真实选项，不生成新地点。

“再来”随机选择，排除本进程记录的该用户当日上一张；没有记录时排除每日默认
卡片。最多保留 256 个 user/day 的上一条故事编号，不存聊天正文；重启、
淘汰或不同工作进程之间不共享上一张。再次无参数调用仍回到固定每日卡片。

正文含标题、标签、帮助和来源机构名共 264–291 个字符，URL 另计。返回
`image_url=None`：本单元提供普通人的生活视角文字，未制作或核对配套人物图片。

## 来源核对（2026-10-06）

下列官网均在本次实际浏览；链接保留在每张卡片。来源只支持对应事实背景，
不证明虚构角色、对话、经历或故事的具体落点年份。

| 落点 | 来源与本次核对的支持范围 |
| --- | --- |
| 两河流域，约公元前1750年 | [耶鲁皮博迪博物馆](https://peabody.yale.edu/explore/collections/yale-babylonian-collection)：巴比伦收藏、食谱泥板；[耶鲁官方馆藏介绍](https://news.yale.edu/2015/11/23/please-pass-hedgehog-pudding-holiday-recipes-yale-s-collections)：约公元前1750年、楔形文字、肉类/蔬菜/炖菜。 |
| 埃及工匠村，约公元前1250年 | [大都会博物馆](https://www.metmuseum.org/essays/an-artisans-tomb-in-new-kingdom-egypt)：新王国墓葬工匠及家人在代尔麦地那居住，尼罗河西岸；列出的相关器物约公元前1290–1224年，仅用于时代范围，1250为虚构故事落点。 |
| 庞贝，约公元79年 | [庞贝考古公园](https://pompeiisites.org/en/archaeological-site/bakery-of-popidio-prisco/)：波皮迪乌斯面包坊的石磨与烤炉、磨麦和烤制环节。不编造该店有直接售卖柜台，官网认为其可能接受订做或批发。79年仅为故事落点。 |
| 唐代长安，约公元750年 | [UNESCO世界遗产中心](https://whc.unesco.org/en/list/1442/)：长安作为汉唐都城及廊道起点、贸易和文化交流；不把虚构布铺与客人当考古记录。 |
| 北宋汴京，约公元1100年 | [故宫藏品条目](https://www.dpm.org.cn/collection/paint/228226.html)：官方检索摘要核对北宋、汴京、汴河和舟车摊贩；另实际浏览[故宫讲坛全文](https://www.dpm.org.cn/forum_detail/99722.html)交叉核对。藏品页面本次正文提取未含动态说明，不宣称取到了全部说明。1100年不是画作的精确创作年。 |
| 江户，约公元1831年 | [大都会博物馆](https://www.metmuseum.org/essays/woodblock-prints-in-the-ukiyo-e-style)：画师/刻工/印工/出版者协作、风景题材；同页列约1830–32年的作品用于时代范围。袖子染色与晾绳是虚构情节。 |
| 伦敦，公元1851年 | [V&A博物馆](https://www.vam.ac.uk/articles/the-great-exhibition-of-1851)：海德公园、1851年万国工业博览会、玻璃与铁构成的水晶宫；裁缝学徒故事重新原创编写。 |
| 犹他，公元1869年 | [美国国家公园管理局](https://www.nps.gov/articles/goldenspike.htm)：1869-05-10、普罗蒙特里山顶、两家铁路接轨、第一条横贯大陆铁路；杂工与水杯为原创虚构。 |

伦敦/犹他取原目录 `bundled.py` 中两条已核对背景作为基础，本次重新浏览官网，
重写原创故事。没有编辑原目录；其余六条在本次选材、核对并创作。

## 实际验证与交接

- Python 3.10.20：指定测试文件 **22 passed，0.30秒**。
- Python 3.13.5：相同测试文件 **22 passed，0.28秒**。
- 覆盖中文组合过滤、未知/冲突选项、跨进程每日稳定、北京时间午夜与 UTC
  换算、用户区分、再来避开上一张、BCE正数格式、八张卡片的史实/虚构标签及
  来源机构和正文长度。没有复制实现算法来构造期望输出，没有实时 HTTP 测试。
- 首轮两环境均 19 passed / 3 failed：修正“两河流域”遗漏的关键词，并让
  跨进程测试按文本模式统一 Windows CRLF；修复后两环境全文件通过。
- 两环境均在内存中编译新 Python 文件、检查三文件尾随空白通过，不生成 pyc。
  传送模块导入新增模块没有 NoneBot、Redis、模型SDK；解释器启动时已存在
  `google` 命名空间，不把该环境预载项误归因于传送依赖。
- 只读 `scripts/audit_structure.py --check`：2026-10-06 12:28 +08:00，
  485文件 / 466文本，0超大文件、0拥挤目录；未使用 --write 修改共享报告。
- 交接局部计数：实现205行、测试107行、本文件97行；所属目录直属文件分别
  5/3/2，不超过10。共享工作区其他实现单元仍可能新增文件。
- 指定三路径的 `git diff --check` 通过；新文件另用实际尾随空白扫描覆盖，
  因未跟踪文件不一定出现在 git diff 中。
- 本单元尚无独立综合评审通过结论；HTTP/插件/发送由主 Agent 集成。
  未验证 QQ 图文呈现、线上使用或多进程防重复；没有启动应用、读取 .env、
  发送 QQ、调用收费模型、Git提交或部署。

回退只撤回上述三个新增文件，不覆盖原草稿、不执行整仓 reset/clean。
