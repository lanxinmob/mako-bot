"""Validate bounded cursor/offset requests independently of storage domains."""
import re


def parse_cursor(cursor, limit):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("invalid page limit")
    if not isinstance(cursor, str) or not re.fullmatch(r"[0-9]{1,20}:[0-9]{1,8}", cursor):
        raise ValueError("invalid page cursor")
    first, offset = map(int, cursor.split(":"))
    if first >= 2**64:
        raise ValueError("invalid page cursor")
    return first, offset
