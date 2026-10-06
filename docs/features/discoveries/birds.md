# 小鸟功能：串行实现单元 2

2026-10-06 12:32 +08:00 开工。重新读取根 AGENTS.md、docs/agent/project.md、docs/agent/development.md、docs/refactor/plan.md、modules.md、status.md 当前批准及本目录 implementation.md；根 development.md 不存在，实际开发指南为 docs/agent/development.md。修改路径下没有更具体 AGENTS.md。

本单元沿用开发者立即完成小鸟功能的明确授权，旧费用/历史独立评审保留待办。共享目录中仅编辑 src/features/discoveries/birds.py、可选语义数据模块 bird_catalog.py、test/features/discoveries/test_birds.py 和本文，不覆盖其他 Agent 的工作。

保留契约：导出 async bird(api: PublicAPI, query: str = '', *, user_id: int = 0, now: datetime | None = None) -> DiscoveryReply；只通过共享 PublicAPI.get 取公开元数据，不注册插件、不调用收费模型、不持久化。固定 iNaturalist 物种检索接口，先校验鸟纲/种级/ID/学名再匹配；歧义明确列候选，实名失败不替换别种。每日选择稳定，网络失败标注离线核对资料。图片仅同种、HTTPS 可信主机、CC0/CC BY/CC BY-SA 且含作者与许可链接；未知许可和 NC 不采用。

验证范围：受控 API/HTTP 替身覆盖身份误配、同名歧义、网络失败、照片关联与许可、日期稳定性；Python 3.10/3.13 定向测试不读取 env。公开网络只用于核对公开来源，不启动应用或发送 QQ。每个本单元文件少于 400 行，discoveries 直属文件不超过 10。

## 完成结果（2026-10-06 12:38 +08:00）

依开发者补充要求，每日池限定为两种已有可复用同种图的鸟，不为凑满 8–12 种引入缺图候选。北京时间日期和 user_id 经 SHA-256 选择，同日同用户及跨进程稳定；无时区 now 视为北京时间。每日联网结果不可核对时仍保留当天选定的同一种鸟，标明离线资料及核对日期，使用该物种的 Commons 图片。

实名查询不限每日池。麻雀/欧亚鸲的已核对中文名映射到完整学名检索；其他中文/学名直接使用固定 taxa 接口及 rank=species、iconic_taxa=Aves、locale=zh-CN、per_page=20。服务实际可能返回非鸟结果，故逐项检查 rank、iconic_taxon_name、正整数 ID、二名学名及已知 ID 对应关系。科学名精确且唯一才选择，中文多候选、单个模糊命中或未读完的中文候选页列出最多六个候选学名供再查。同一 ID 的冲突数据不使用；实名无结果/来源故障明确反馈，不替换成每日鸟。

照片来自已确认物种的 taxon_photos 或 default_photo；若存在显式 taxon_id/taxon 关联则必须同种。逐图拒绝错误 ID、未署名、版权标记、NC/ND/未知许可、许可链接冲突、非 HTTPS/非 iNaturalist 媒体主机或图片路径 ID 不符。只接受 cc0、cc-by、cc-by-sa；图文附作者、许可版本/链接、照片来源和缩略图说明。Commons 兜底只绑定两个已核对的学名与 ID，其他鸟没有合格图仍返回物种来源。中文名缺失不翻译或猜造；两个固定科普片段有来源，其余只给真实分类与资料链接。

实现仅请求 https://api.inaturalist.org/v1/taxa；不请求来源返回的 Wikipedia URL。百科链接只接受 en.wikipedia.org/zh.wikipedia.org 的 /wiki/ 路径，拒绝认证、端口、查询参数、fragment 和异常字符，可将这两个已知主机的 HTTP 展示链接改为 HTTPS。

## 本次核对的来源

- iNaturalist 公开 taxa 查询：Passer montanus = 麻雀、13851、species/Aves，默认照片为 cc-by-nc；Erithacus rubecula = 欧亚鸲、13094、species/Aves，默认照片许可为空。两者本次查询没有 taxon_photos 字段，不使用不合格默认照。此为公开无认证检索，httpx trust_env=False。
- [麻雀 Commons 文件页](https://commons.wikimedia.org/wiki/File:Passer_montanus_(13955614566).jpg)：xulescu_g、[CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0/)。从当前文件页 330px 预览链接核对实际地址为 `https://thumb.wikimedia.org/wikipedia/commons/thumb/2/28/Passer_montanus_%2813955614566%29.jpg/330px-Passer_montanus_%2813955614566%29.jpg`，未沿用旧 draft 路径。本机直接连接该媒体主机 TLS 握手超时，未宣称图片下载或 QQ 发送成功；许可、物种和预览 URL 依据文件页核对。
- [欧亚鸲 Commons 文件页](https://commons.wikimedia.org/wiki/File:Erithacus_rubecula_profile.jpg)：C-M、[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)，文件页 500px 预览链接为 `https://thumb.wikimedia.org/wikipedia/commons/thumb/4/47/Erithacus_rubecula_profile.jpg/500px-Erithacus_rubecula_profile.jpg`。
- 麻雀辨认/食性：[Cornell All About Birds](https://www.allaboutbirds.org/guide/Eurasian_Tree_Sparrow/overview)，仅概括页面的栗色头顶、白色脸颊、树篱/农场及种子信息。
- 欧亚鸲成幼鸟辨认：[RSPB Robin](https://www.rspb.org.uk/birds-and-wildlife/robin)，仅概括红胸、褐背及幼鸟特征。
- iNaturalist 许可版本：[官方 Shared::LicenseModule](https://raw.githubusercontent.com/inaturalist/inaturalist/main/app/models/shared/license_module.rb)，CC_VERSION=4.0、CC0_VERSION=1.0；动态 API 的许可代码链接采用该官方映射。

## 验证与交接

- Python 3.10：`..\.refactor-snapshots\validation-py310\Scripts\python.exe -B -m pytest -q -p no:cacheprovider test/features/discoveries/test_birds.py`，61 passed，1.04s。
- Python 3.13：`..\mako-bot\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider test/features/discoveries/test_birds.py`，61 passed，1.23s。首次 3.10 执行发现日期测试自身用了 async_generator 喂给 any，已修为显式 await 列表后两端通过，未削弱断言。
- 验证含真实 PublicAPI/MockTransport 契约、两种每日卡联网/离线同图、所有允许许可、NC/ND/未知拒绝、显式关联误配、坏 rank/iconic/ID/学名、歧义/分页、来源故障/坏日期、北京午夜、跨进程稳定及取消透传。测试未读取 env 或启动应用，无真实外部请求。
- 四个本单元文件：birds.py 249 行、bird_catalog.py 55 行、test_birds.py 271 行，本文少于 400 行。完成时 discoveries 源码 9 个直属文件、测试 5 个、文档 4 个，均不超过 10；范围限定的 git diff --check 通过。
- 交付文件即本单元允许的四个路径；共享 network/models/service/plugin 由主 Agent 负责，不修改原 mako-bot。只增添鸟种数据、处理函数和定向测试，不引入框架/缓存/持久化。
- 本单元实现与必要验证已完成；独立综合评审、真实媒体下载可用性及 QQ 体验由后续集成验证，未冒称已验收。回退可仅撤回本单元四个新文件，主 Agent 同时处理服务入口对应关系，不覆盖其他工作。
