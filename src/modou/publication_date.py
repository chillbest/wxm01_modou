"""Shared source-date inference for parsing and review display."""
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import date


def infer_publication_date(source, title, now=None):
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if now.tzinfo is not None:
        now = now.astimezone(ZoneInfo('Asia/Shanghai'))
    filename = '' if source.startswith(('http://', 'https://')) else Path(source).name
    for text in (filename, title):
        match = re.search(r'(?:(20\d{2})[年./_-])?(\d{1,2})[月./_-](\d{1,2})(?:日)?', text)
        if match:
            try:
                return date(int(match[1] or now.year), int(match[2]), int(match[3]))
            except ValueError:
                continue
    return None
