"""Real journal identities and recent article evidence from public Crossref data."""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import re
from unicodedata import normalize
from urllib.parse import quote

from .journal_catalog import CHECKED_ON, NAME_ISSNS, NAMED_ONLY, SEEDS, TOPICS
from .models import DiscoveryReply, clean
from .network import LookupUnavailable, PublicAPI

BASE = "https://api.crossref.org"
_SELECT = "DOI,title,container-title,ISSN,publisher,published,type"


def _day(now: datetime | None) -> date:
    moment = now or datetime.now(timezone(timedelta(hours=8)))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone(timedelta(hours=8)))
    return moment.astimezone(timezone(timedelta(hours=8))).date()


def _query(value: str) -> str:
    value = normalize("NFKC", value).strip()
    if len(value) > 100 or any(ord(c) < 32 for c in value):
        raise ValueError("查询请用100字以内的刊名、ISSN或研究主题。")
    return value


def _two_years_before(day: date) -> date:
    try:
        return day.replace(year=day.year - 2)
    except ValueError:
        return day.replace(year=day.year - 2, day=28)


def valid_issn(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    compact = value.replace("-", "").upper()
    if not re.fullmatch(r"\d{7}[\dX]", compact, flags=re.ASCII):
        return None
    digits = [int(c) if c != "X" else 10 for c in compact]
    if sum(digit * weight for digit, weight in zip(digits, range(8, 0, -1))) % 11:
        return None
    return compact[:4] + "-" + compact[4:]


def _issns(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(issn for raw in value[:10] if (issn := valid_issn(raw))))


def _message(payload: dict) -> dict:
    message = payload.get("message")
    if payload.get("status") != "ok" or not isinstance(message, dict):
        raise LookupUnavailable("期刊来源没有返回可核对元数据")
    return message


def _items(payload: dict) -> list[dict]:
    value = _message(payload).get("items")
    if not isinstance(value, list):
        raise LookupUnavailable("期刊来源没有返回条目列表")
    return [row for row in value[:60] if isinstance(row, dict)]


def _identity(row: dict, expected: str | None = None) -> dict | None:
    title, issns = clean(row.get("title"), 160), _issns(row.get("ISSN"))
    if not title or not issns or (expected is not None and expected not in issns):
        return None
    return {"title": title, "issns": issns,
            "publisher": clean(row.get("publisher"), 110) or "来源未记录"}


def _first(value: object, limit: int = 160) -> str:
    if isinstance(value, list) and value:
        return clean(value[0], limit)
    return ""


def _article(row: dict, start: date, end: date) -> dict | None:
    title, container = _first(row.get("title")), _first(row.get("container-title"))
    doi = row.get("DOI")
    if (row.get("type") != "journal-article" or not title
            or title.casefold() in {"front cover", "back cover", "editorial", "contents", "table of contents"}
            or not isinstance(doi, str) or len(doi) > 250
            or not re.fullmatch(r"10\.\d{4,9}/[^\s]+", doi, flags=re.ASCII)):
        return None
    published = row.get("published")
    parts = published.get("date-parts") if isinstance(published, dict) else None
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
        return None
    values = parts[0]
    if not 1 <= len(values) <= 3 or any(type(v) is not int for v in values):
        return None
    try:
        earliest = date(values[0], values[1] if len(values) > 1 else 1,
                        values[2] if len(values) > 2 else 1)
        # Unknown month/day cannot establish a date beyond the precision supplied.
        if len(values) == 1:
            latest = date(values[0], 12, 31)
        elif len(values) == 2:
            following = (date(values[0] + 1, 1, 1) if values[1] == 12 else
                         date(values[0], values[1] + 1, 1))
            latest = following - timedelta(days=1)
        else:
            latest = earliest
    except (ValueError, OverflowError):
        return None
    if earliest > end or latest < start:
        return None
    return {"title": title, "container": container, "issns": _issns(row.get("ISSN")),
            "publisher": clean(row.get("publisher"), 100) or "来源未记录",
            "date": "-".join(str(v).zfill(4 if i == 0 else 2) for i, v in enumerate(values)),
            "url": "https://doi.org/" + quote(doi, safe="/")}


async def _card(api: PublicAPI, row: dict, fetched: str, day: date) -> DiscoveryReply:
    issn = row["issns"][0]
    lines = [f"📚 期刊｜{row['title']}", "ISSN：" + " / ".join(row["issns"]),
             "出版方（Crossref记录）：" + row["publisher"]]
    seed = next((s for s in (*SEEDS, *NAMED_ONLY) if s.issn in row["issns"]), None)
    if seed is not None:
        lines.extend(["范围：" + seed.scope, f"范围来源（核对{CHECKED_ON}）：{seed.source}",
                      "投稿说明：" + seed.instructions])
    start = _two_years_before(day)
    try:
        payload, papers_date = await api.get(f"{BASE}/journals/{issn}/works", {
            "rows": 6, "sort": "published", "order": "desc", "select": _SELECT,
            "filter": f"type:journal-article,from-pub-date:{start},until-pub-date:{day}"})
        articles = [_article(item, start, day) for item in _items(payload)]
        # The journal endpoint already fixes identity; metadata still must agree.
        articles = [a for a in articles if a and issn in a["issns"]][:2]
        if articles:
            lines.append(f"近期文章例证（获取{papers_date}）：")
            lines.extend(f"• {a['title']}（{a['date']}）\n{a['url']}" for a in articles)
            lines.append("Crossref文章类型不区分研究与新闻，请打开原文核对。")
        else:
            lines.append("近两年暂无可核对文章例证；这不表示刊物没有发表文章。")
    except LookupUnavailable:
        lines.append("刊物身份已查到；近期论文来源暂不可用。")
    lines.extend([f"元数据来源（获取{fetched}）：{BASE}/journals/{issn}",
                  "分区、影响因子、版面费：本功能未核验；请查刊物官网。"])
    return DiscoveryReply("\n".join(lines))


async def journal(api: PublicAPI, query: str = "", *, user_id: int = 0,
                  now: datetime | None = None) -> DiscoveryReply:
    query, day = _query(query), _day(now)
    if not query:
        digest = sha256(f"journal:{user_id}:{day}".encode()).digest()
        query = SEEDS[int.from_bytes(digest, "big") % len(SEEDS)].issn
    query = re.sub(r"^ISSN\s*:?\s*", "", query, flags=re.IGNORECASE)
    issn = valid_issn(query) or NAME_ISSNS.get(query.casefold())
    if not issn and re.fullmatch(r"[\dXx\- ]{7,12}", query, flags=re.ASCII):
        raise ValueError("ISSN格式或校验位不正确，例如：期刊 1932-6203。")
    if issn:
        payload, fetched = await api.get(f"{BASE}/journals/{issn}")
        row = _identity(_message(payload), issn)
        if row is None:
            raise LookupUnavailable("来源返回的刊物与ISSN不匹配")
        return await _card(api, row, fetched, day)
    payload, fetched = await api.get(f"{BASE}/journals", {"query": query, "rows": 30})
    rows = [row for raw in _items(payload) if (row := _identity(raw))]
    exact = [row for row in rows if row["title"].casefold() == query.casefold()]
    if len(exact) == 1:
        return await _card(api, exact[0], fetched, day)
    choices = exact if exact else rows
    if not choices:
        return DiscoveryReply("没找到可核对的刊物。试试完整英文刊名或ISSN，例如：期刊 1932-6203。")
    lines = ["找到这些候选，请用ISSN确认："]
    for row in choices[:3]:
        lines.append(f"• {row['title']}｜{row['publisher']}\n期刊 {row['issns'][0]}")
    lines.append(f"来源（获取{fetched}）：https://search.crossref.org/?q={quote(query, safe='')}")
    return DiscoveryReply("\n".join(lines))


async def suggest(api: PublicAPI, query: str = "", *, user_id: int = 0,
                  now: datetime | None = None) -> DiscoveryReply:
    query = _query(query)
    if not query:
        reply = await journal(api, user_id=user_id, now=now)
        return DiscoveryReply("今天认识一本真实期刊；也可发送“投稿 研究主题”找相关文章。\n" + reply.text)
    day = _day(now)
    start = _two_years_before(day)
    terms = TOPICS.get(query, query)
    payload, fetched = await api.get(f"{BASE}/works", {
        "query.bibliographic": terms, "rows": 30, "sort": "relevance", "select": _SELECT,
        "filter": f"type:journal-article,from-pub-date:{start},until-pub-date:{day}"})
    groups, seen = [], set()
    for raw in _items(payload):
        article = _article(raw, start, day)
        if not article or not article["container"] or not article["issns"]:
            continue
        key = article["container"].casefold()
        if key not in seen:
            groups.append(article)
            seen.add(key)
        if len(groups) == 3:
            break
    if not groups:
        return DiscoveryReply("近两年没找到带刊名、有效ISSN和DOI的相关文章。试试更具体的英文主题，或发送“期刊 刊名”。")
    label = f"{clean(query)} → {terms}" if query != terms else clean(query)
    lines = [f"🔎 主题：{label}", f"检索范围：{start}—{day}；按文章相关性取样。"]
    for i, article in enumerate(groups, 1):
        lines.extend([f"{i}. {article['container']}｜{article['publisher']}",
                      f"例证：{article['title']}（{article['date']}）", article["url"],
                      f"继续查：期刊 {article['issns'][0]}"])
    lines.extend([f"来源（获取{fetched}）：https://search.crossref.org/?q={quote(terms, safe='')}",
                  "这些是相关文章对应刊物，不代表质量排名或录用概率；投稿前核对官网范围与要求。"])
    return DiscoveryReply("\n".join(lines))
