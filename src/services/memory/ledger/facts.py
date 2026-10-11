"""Finite first-person rules. A subject hash never acts as an ownership token."""
import hashlib
import re


def normalized(text):
    return re.sub(r'[\s。！!？?，,、：:]', '', text).casefold()


def subject(kind, topic):
    return hashlib.sha256((kind + ':' + normalized(topic)).encode()).hexdigest()


def preference(text):
    text = text.strip().rstrip('。.!！?？')
    patterns = (
        (r'以前喜欢(.+)，?现在不喜欢了', '不喜欢'),
        (r'(?:我)?(?:现在)?不喜欢(.+?)(?:了)?', '不喜欢'),
        (r'我讨厌(.+)', '讨厌'), (r'我(?:喜欢|爱)(.+)', '喜欢'),
        (r'(喜欢|不喜欢|讨厌)[：:](.+)', None),
    )
    for pattern, attitude in patterns:
        match = re.fullmatch(pattern, text)
        if match:
            topic = (match.group(1) if attitude else match.group(2)).strip(' ，,')
            if not topic:
                return None
            attitude = attitude or match.group(1)
            if any(token in topic for token in ('他说', '她说', '开玩笑', '密码', '令牌', 'http', '“', '”', '\n', '[CQ:')):
                return None
            return dict(memory_type='preference', content=f'{attitude}：{topic}',
                        subject_key=subject('preference', topic))
    return None


def fact(text, kind=None):
    if any(token in text for token in ('开玩笑', '密码', '令牌', 'http', '[CQ:', '“', '”', '\n')):
        return None
    found = preference(text)
    if found and kind in (None, 'preference'):
        return found
    if kind == 'preference':
        return None
    match = re.fullmatch(r'(?:以后不要|请别|别再|我不希望你|不要叫我|不许叫我)(.+)', text.strip().rstrip('。!！'))
    if match and kind in (None, 'taboo'):
        topic = match.group(1)
        return dict(memory_type='taboo', content=topic, subject_key=subject('taboo', topic))
    if text.strip().startswith(('提醒我', '记得提醒我', '回头问我', '之后问我', '帮我跟进')) and kind in (None, 'promise'):
        return dict(memory_type='promise', content=text.strip(), subject_key=subject('promise', text))
    if kind in ('event', 'taboo', 'promise') and text.strip():
        return dict(memory_type=kind, content=text.strip(), subject_key=subject(kind, text))
    return None
