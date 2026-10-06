"""Small, dated discovery pool; scope summaries link to publisher sources."""
from dataclasses import dataclass


@dataclass(frozen=True)
class JournalSeed:
    title: str
    issn: str
    scope: str
    source: str
    instructions: str


CHECKED_ON = "2026-10-06"
SEEDS = (
    JournalSeed("PLOS One", "1932-6203",
                "涵盖自然科学、医学、工程及相关社会科学；重视研究有效性、方法与伦理。",
                "https://journals.plos.org/plosone/s/journal-information",
                "https://journals.plos.org/plosone/s/submission-guidelines"),
    JournalSeed("Scientific Reports", "2045-2322",
                "自然科学、心理学、医学和工程领域的原创研究。",
                "https://www.nature.com/srep/about/aims",
                "https://www.nature.com/srep/author-instructions/submission-guidelines"),
    JournalSeed("IEEE Access", "2169-3536",
                "IEEE所覆盖科技领域的跨学科原创研究与开发成果。",
                "https://ieeeaccess.ieee.org/",
                "https://ieeeaccess.ieee.org/guide-for-authors/"),
    JournalSeed("Royal Society Open Science", "2054-5703",
                "覆盖科学、工程及数学，包含Registered Reports和重复研究。",
                "https://royalsociety.org/journals/authors/which-journal/",
                "https://royalsociety.org/journals/authors/author-guidelines/"),
    JournalSeed("BMC Bioinformatics", "1471-2105",
                "用于生物数据分析与系统生物学的计算算法、模型、软件和工具。",
                "https://link.springer.com/journal/12859/aims-and-scope",
                "https://link.springer.com/journal/12859/submission-guidelines"),
    JournalSeed("PLOS Computational Biology", "1553-7358",
                "运用计算方法理解生物系统，研究、方法与软件需提供生物学或方法学进展。",
                "https://journals.plos.org/ploscompbiol/s/journal-information",
                "https://journals.plos.org/ploscompbiol/s/submission-guidelines"),
)

NAMED_ONLY = (
    JournalSeed("Nature", "1476-4687", "跨学科科学与技术研究，关注超出单一学科的意义。",
                "https://www.nature.com/nature/journal-information",
                "https://www.nature.com/nature/for-authors/initial-submission"),
)

NAME_ISSNS = {seed.title.casefold(): seed.issn for seed in (*SEEDS, *NAMED_ONLY)}
NAME_ISSNS.update({"自然": "1476-4687",
                   "科学报告": "2045-2322", "生物信息学": "1471-2105"})
TOPICS = {"机器学习": "machine learning", "深度学习": "deep learning",
          "机器人": "robotics", "机器人学习": "robot learning",
          "计算机视觉": "computer vision", "地质": "geology",
          "材料": "materials science", "生物信息": "bioinformatics",
          "生物信息学": "bioinformatics", "教育": "education"}
