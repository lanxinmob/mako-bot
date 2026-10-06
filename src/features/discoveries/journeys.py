"""Offline historical backgrounds with clearly separated original fiction."""

from dataclasses import dataclass
from datetime import datetime
import re
from unicodedata import normalize

from .models import DiscoveryReply
from .selection import ChoiceCycle

__all__ = ["journey"]

_CHECKED_ON = "2026-10-06"
_CHOICES = ChoiceCycle()


@dataclass(frozen=True)
class _Source:
    title: str
    url: str


@dataclass(frozen=True)
class _Journey:
    key: str
    title: str
    year: int  # Negative means BCE; there is no year zero.
    era: str
    place: str
    keywords: tuple[str, ...]
    backdrop: str
    story: str
    sources: tuple[_Source, ...]
    approximate: bool = True


_JOURNEYS = (
    _Journey(
        key="mesopotamia-stew", title="泥板上没有写放几勺",
        year=-1750, era="古巴比伦时期", place="西亚 · 两河流域",
        keywords=("两河", "两河流域", "巴比伦", "古巴比伦", "伊拉克", "西亚", "亚洲", "古代", "公元前"),
        backdrop="耶鲁收藏的约公元前1750年食谱泥板，以楔形文字记录了肉类、蔬菜和炖菜的做法。",
        story="你是厨房帮工。师傅叫你盯住炖锅，你却认真练起了搅汤的姿势。"
        "同伴尝了一口，问你是不是把锅当成了河流。你赶紧添料，忙到天黑才端出一碗像样的汤。"
        "师傅没夸手艺，只把最后一块饼留给你：下回先尝，再摆架势。",
        sources=(
            _Source("耶鲁皮博迪博物馆 · 巴比伦收藏",
                    "https://peabody.yale.edu/explore/collections/yale-babylonian-collection"),
            _Source("耶鲁官方 · 古代食谱年代与内容",
                    "https://news.yale.edu/2015/11/23/please-pass-hedgehog-pudding-holiday-recipes-yale-s-collections"),
        ),
    ),
    _Journey(
        key="egypt-painter", title="一只画歪的鹅",
        year=-1250, era="古埃及新王国", place="埃及 · 代尔麦地那工匠村",
        keywords=("埃及", "古埃及", "新王国", "代尔麦地那", "非洲", "古代", "公元前"),
        backdrop="代尔麦地那住着开凿、装饰王室墓葬的工匠及其家人；村址位于尼罗河西岸。",
        story="你是画工学徒，收工后在废陶片上练习画鹅。第一只像壶，第二只像师傅的鞋。"
        "邻居小孩偏偏看中了第二只，抱回去说它能赶走坏梦。第二天你认真画出第三只，"
        "小孩却摇头：还是昨天那只凶。你把陶片收好，第一次觉得画歪也有用。",
        sources=(_Source("大都会博物馆 · 新王国工匠的墓葬",
                         "https://www.metmuseum.org/essays/an-artisans-tomb-in-new-kingdom-egypt"),),
    ),
    _Journey(
        key="pompeii-bread", title="面包送到，香味留下",
        year=79, era="古罗马时期", place="意大利 · 庞贝",
        keywords=("罗马", "古罗马", "意大利", "庞贝", "欧洲", "古代"),
        backdrop="庞贝的波皮迪乌斯面包坊遗址保留了石磨和烤炉，呈现磨麦到烤面包的生产环节。",
        story="你替面包坊跑腿，今天最大的难题是让篮子一路保持完整。街口熟人说要帮你闻闻熟没熟，"
        "你抱紧篮子：鼻子可以，手不行。送完货回来，师傅给你一小块边角。"
        "你故意绕回街口，分了一半给那位只准用鼻子的朋友。",
        sources=(_Source("庞贝考古公园 · 波皮迪乌斯面包坊",
                         "https://pompeiisites.org/en/archaeological-site/bakery-of-popidio-prisco/"),),
    ),
    _Journey(
        key="changan-cloth", title="不用出城的小旅行",
        year=750, era="唐代", place="中国 · 长安（今西安）",
        keywords=("中国", "中國", "唐", "唐朝", "唐代", "长安", "西安", "陕西",
                  "丝绸之路", "亚洲", "古代"),
        backdrop="长安是唐代都城，也是丝绸之路长安—天山廊道的起点之一；贸易带来远方的货物与交流。",
        story="你是布铺学徒，给一位远来的客人找遗落的布包。你俩语言不通，"
        "他比划了半天，你端来了水，他终于笑着指向柜台底下。包找到了，"
        "里面只有旧衣和一双补过的鞋。你原以为远方都装着宝物，收工时却先给自己的鞋补了两针。",
        sources=(_Source("联合国教科文组织 · 长安—天山廊道",
                         "https://whc.unesco.org/en/list/1442/"),),
    ),
    _Journey(
        key="bianjing-delivery", title="过桥前先护住午饭",
        year=1100, era="北宋", place="中国 · 汴京（今开封）",
        keywords=("中国", "中國", "宋", "宋朝", "宋代", "北宋", "汴京", "东京",
                  "开封", "河南", "亚洲", "古代"),
        backdrop="故宫所藏北宋《清明上河图》描绘汴京及汴河沿岸的生活，画中可见舟车、摊贩与行人。",
        story="你是店里的送货伙计，过桥时只顾看船，差点把午饭挤进别人袖口。"
        "卖小物件的老人帮你托住包袱，收的报酬是一声谢谢。回程你替他搬了一趟凳子。"
        "掌柜问怎么去了这么久，你答：货送一趟，谢得送回来。",
        sources=(_Source("故宫博物院 · 张择端清明上河图卷",
                         "https://www.dpm.org.cn/collection/paint/228226.html"),),
    ),
    _Journey(
        key="edo-print", title="晾不干的远方",
        year=1831, era="江户时代", place="日本 · 江户（今东京）",
        keywords=("日本", "江户", "江户时代", "东京", "亚洲", "近代", "十九世纪", "19世纪"),
        backdrop="江户时期的木版画由画师、刻工、印工和出版者协作制作，题材逐渐扩展到风景。",
        story="你是印坊学徒，负责把刚印好的纸摊开。雨要来了，你抱着一摞风景找干地方，"
        "却把袖子染得比画还鲜艳。邻居问你去过画里的山吗。你低头看袖口："
        "没去过，不过今天搬了它十七回。她给你腾出一条晾绳，你顺便替她把衣服收进屋。",
        sources=(_Source("大都会博物馆 · 浮世绘木版画",
                         "https://www.metmuseum.org/essays/woodblock-prints-in-the-ukiyo-e-style"),),
    ),
    _Journey(
        key="london-1851", title="水晶宫带回一截袖口",
        year=1851, era="维多利亚时代", place="英国 · 伦敦海德公园",
        keywords=("英国", "伦敦", "海德公园", "水晶宫", "维多利亚", "维多利亚时代",
                  "欧洲", "近代", "十九世纪", "19世纪"),
        backdrop="1851年，万国工业博览会在伦敦海德公园举行，玻璃与铁构成的展馆被称为水晶宫。",
        story="你是裁缝铺学徒，攒下半天休息去看展。机器太多，你倒记住了一个袖口花纹，"
        "画在包午饭的纸背面。回铺里师傅问看到了什么了不起的发明。"
        "你摊开带着油印的纸：这个，我想试试。师傅笑着推来一截边角料。",
        sources=(_Source("V&A博物馆 · 1851年万国工业博览会",
                         "https://www.vam.ac.uk/articles/the-great-exhibition-of-1851"),),
        approximate=False,
    ),
    _Journey(
        key="promontory-1869", title="欢呼声里的水杯",
        year=1869, era="十九世纪", place="美国 · 犹他普罗蒙特里山顶",
        keywords=("美国", "犹他", "普罗蒙特里", "北美", "近代", "十九世纪", "19世纪", "铁路"),
        backdrop="1869年5月10日，中央太平洋与联合太平洋铁路在这里接轨，美国第一条横贯大陆铁路完成。",
        story="你是来帮忙的杂工。人群挤着看仪式，你蹲下找滚走的水杯。"
        "陌生人替你挡住脚步，远处欢呼时你终于摸到杯子。散场后你分他一小块面包，"
        "两人聊起今晚去哪儿洗衣服。你记不清最后一锤的声音，倒记住了他替你掸掉背上灰土的手。",
        sources=(_Source("美国国家公园管理局 · 金钉接轨仪式",
                         "https://www.nps.gov/articles/goldenspike.htm"),),
        approximate=False,
    ),
)


def _matches(item: _Journey, query: str) -> bool:
    # Every part must be a supported keyword: 中国唐朝 works; 中国火星 does not.
    remainder = re.sub(r"[\s,，、/·]+", "", query)
    aliases = (*item.keywords, item.era, item.title)
    for keyword in sorted(set(aliases), key=lambda value: (-len(value), value)):
        remainder = remainder.replace(keyword, "")
    return not remainder


def _render(item: _Journey) -> DiscoveryReply:
    year = f"公元前{abs(item.year)}年" if item.year < 0 else f"公元{item.year}年"
    if item.approximate:
        year = "约" + year
    text = (
        f"🧭 睁开眼，你到了……\n{year} · {item.era}\n{item.place}\n\n"
        f"「{item.title}」\n小故事（虚构）：{item.story}\n\n"
        f"历史背景：{item.backdrop}\n"
        f"背景出处（核对{_CHECKED_ON}）：\n"
    )
    text += "\n".join(f"{source.title}：{source.url}" for source in item.sources)
    return DiscoveryReply(text=text)


def journey(
    query: str = "", *, user_id: int = 0, now: datetime | None = None
) -> DiscoveryReply:
    """Draw a new story, optionally filtered by region or era."""
    query = normalize("NFKC", query).strip()
    if query == "再来":
        query = ""
    candidates = tuple(item for item in _JOURNEYS if not query or _matches(item, query))
    if not candidates:
        return DiscoveryReply(
            text="还没有符合这些关键词的故事。可选：两河流域、埃及、庞贝、唐代长安、"
            "北宋汴京、日本江户、英国伦敦、美国犹他。也可用：中国、古代、近代、"
            "公元前、十九世纪；组合示例：传送 中国 唐代。发送“传送 再来”可随机换一站。"
        )
    key = _CHOICES.choose(user_id, tuple(item.key for item in candidates))
    selected = next(item for item in candidates if item.key == key)
    return _render(selected)
