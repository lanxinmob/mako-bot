"""Verified species and reusable photos; each record owns its exact species image."""
from dataclasses import dataclass


VERIFIED_DAY = "2026-10-06"


@dataclass(frozen=True)
class BirdPhoto:
    url: str
    author: str
    license_name: str
    license_url: str
    source: str


@dataclass(frozen=True)
class BirdRecord:
    name: str
    chinese_name: str
    taxon_id: int
    note: str
    source: str
    photo: BirdPhoto


# Chinese names, rank, Aves and IDs checked against iNaturalist taxa on VERIFIED_DAY.
# Daily selection is deliberately limited to species with verified reusable images.
DAILY_BIRDS = (
    BirdRecord(
        "Passer montanus", "麻雀", 13851,
        "辨认线索：栗色头顶、白色脸颊。常在树篱和农场附近活动；以种子为食。",
        "https://www.allaboutbirds.org/guide/Eurasian_Tree_Sparrow/overview",
        BirdPhoto(
            "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/28/"
            "Passer_montanus_%2813955614566%29.jpg/"
            "330px-Passer_montanus_%2813955614566%29.jpg",
            "xulescu_g", "CC BY-SA 2.0",
            "https://creativecommons.org/licenses/by-sa/2.0/",
            "https://commons.wikimedia.org/wiki/File:Passer_montanus_(13955614566).jpg",
        ),
    ),
    BirdRecord(
        "Erithacus rubecula", "欧亚鸲", 13094,
        "辨认线索：成鸟胸部鲜红、背部褐色；幼鸟尚无红胸，羽毛有褐色斑点。",
        "https://www.rspb.org.uk/birds-and-wildlife/robin",
        BirdPhoto(
            "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/47/"
            "Erithacus_rubecula_profile.jpg/500px-Erithacus_rubecula_profile.jpg",
            "C-M", "CC BY-SA 4.0",
            "https://creativecommons.org/licenses/by-sa/4.0/",
            "https://commons.wikimedia.org/wiki/File:Erithacus_rubecula_profile.jpg",
        ),
    ),
)
