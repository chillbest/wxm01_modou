from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4
import pytest
from modou.publication_date import infer_publication_date
from modou.note_review import build_review
from modou.review_html import write_html
from test_note_review import Local, API


@pytest.mark.parametrize('source,title,expected', [
 ('11.3A｜PS.txt','11.4｜PS',date(2026,11,3)),
 ('sample.txt','2025-11-04｜PS',date(2025,11,4)),
 ('https://example.com/12.9','11.4｜PS',date(2026,11,4)),
 ('2.30.txt','11.4｜PS',date(2026,11,4)),
 ('sample.txt','PS',None),
])
def test_inference(source,title,expected):
    assert infer_publication_date(source,title,datetime(2026,11,16)) == expected


def test_year_uses_shanghai_timezone():
    assert infer_publication_date('1.2.txt','',datetime(2025,12,31,18,tzinfo=timezone.utc)) == date(2026,1,2)


@pytest.mark.parametrize('explicit', [None,date(2024,10,2)])
def test_review_payload_and_page_share_date(explicit):
    from datetime import datetime
    year = datetime.now().year
    expected = explicit or date(year,11,3)
    rows=build_review('11.4｜PS好价光盘\n————实时新增————\n合金弹头7 PS4｜HK100',
                      '11.3A｜PS好价光盘.txt',explicit,[],Local(),API())
    row=rows[0]
    assert row['quote']['published_at'] == expected.isoformat()
    assert row['quote']['lowprice_date'] == expected.isoformat()
    assert row['extracted']['lowprice_date'] == expected.isoformat()
    assert '日期待确认' not in row['extracted']['issues']
    directory=Path('.tmp') / ('dates-'+uuid4().hex)
    directory.mkdir(parents=True)
    output=write_html(rows,'11.3A｜PS好价光盘.txt','11.4｜PS好价光盘',directory)
    assert '出价日'+expected.strftime('%Y/%m/%d') in output.read_text(encoding='utf-8')


def test_explicit_quote_date_preserved():
    rows=build_review('PS好价光盘\n————实时新增————\n合金弹头7 PS4｜HK100｜2025-10-01',
                      '11.3.txt',date(2026,11,3),[],Local(),API())
    assert rows[0]['quote']['published_at']=='2026-11-03'
    assert rows[0]['quote']['lowprice_date']=='2025-10-01'


def test_unknown_date_remains_pending():
    rows=build_review('PS好价光盘\n————实时新增————\n合金弹头7 PS4｜HK100',
                      'sample.txt',None,[],Local(),API())
    assert rows[0]['quote']['published_at'] is None
    assert rows[0]['quote']['lowprice_date'] is None
    assert '日期待确认' in rows[0]['extracted']['issues']
    directory=Path('.tmp') / ('dates-'+uuid4().hex)
    directory.mkdir(parents=True)
    output=write_html(rows,'sample.txt','PS好价光盘',directory)
    assert '出价日待确认' in output.read_text(encoding='utf-8')
