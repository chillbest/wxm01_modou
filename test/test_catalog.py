"""GPC persistence assertions; price-query adaptation remains deferred."""
from datetime import date
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_gpc_schema import connection
from modou.observations import save_observation


def test_gpc_quotes_platforms_and_source_reuse(connection):
    identity = connection.scalar(text("insert into game_product_config(name_zh) values ('game') returning gpc_id"))
    with Session(bind=connection) as session:
        fields = dict(source_path='data/note.txt',gpc_id=identity,region='港版',lowprice_cny=100,
                      lowprice_date=date(2026,11,13),lowprice_method='直接购买',published_at=date(2026,11,13))
        first = save_observation(session,platform='PS5',**fields)
        assert save_observation(session,platform='PS5',**fields).record_id == first.record_id
        assert save_observation(session,platform='PS4',**fields).record_id != first.record_id
        assert save_observation(session,platform='Switch',**fields).platform == 'Switch'
    assert connection.scalar(text('select count(*) from data_source')) == 1
    assert connection.scalar(text('select count(*) from m_low_record')) == 3
