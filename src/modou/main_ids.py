"""Canonical storage for one or more Bangumi main IDs."""
import re


def normalize_main(value):
    if value is None or value == '':
        return None
    if not isinstance(value, str):
        raise ValueError('main须为数字ID，多个ID用|分隔')
    if value.isspace():
        return None
    parts = [part.strip() for part in value.split('|')]
    if not all(re.fullmatch(r'[0-9]+', part) and int(part) > 0 for part in parts):
        raise ValueError('main须为正整数ID，多个ID用|分隔，不得有空项')
    return '|'.join(dict.fromkeys(str(int(part)) for part in parts))
