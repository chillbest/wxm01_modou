import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from modou.catalog_memory import load_aliases, read_test_catalog, test_database_url as guarded_url
from modou.deepseek import CachedSuggestions
from modou.local_config import read_config
from modou.models import GameName, GameVariant, GameAlias, PriceRecord, DataSource
from modou.parsing import CatalogEntry, parse_note


@pytest.fixture
def workdir():
    from uuid import uuid4
    path = Path('.tmp') / ('m02-memory-test-' + uuid4().hex)
    path.mkdir(parents=True)
    return path


def parse(name, catalog=(), suggest=None):
    return parse_note(f"标题\n————福8-80区————\n{name}｜🇭🇰265｜史低257",
                      published_date=date(2026, 11, 3), catalog=catalog, suggest=suggest).items[0]


def entry(**kwargs):
    return CatalogEntry(name_zh="标准游戏", name_id=1, aliases=["简称"], **kwargs)


def test_entry_point_is_alias_only():
    catalog = [entry()]
    assert parse("简称", catalog).name_id == 1
    assert parse("标准游戏", catalog).match_status == "unmatched"
    assert parse("标准游戏", [entry().model_copy(update={"aliases": ["标准游戏"]})]).match_status == "alias"


def test_game_alias_does_not_infer_spec():
    item = parse("简称", [entry()])
    assert item.match_status == "alias"
    assert item.variant_id is item.platform is item.edition is None
    assert item.review_status == "pending"
    assert item.notes == ["史低257"]


def test_variant_alias_reuse_skips_ai():
    def forbidden(_):
        pytest.fail("可靠命中不得调用AI")
    item = parse("简称", [entry(variant_id=2, platform="PS5", edition="完全版")], forbidden)
    assert (item.name_id, item.variant_id, item.platform, item.edition) == (1, 2, "PS5", "完全版")
    assert item.review_status == "pending"


@pytest.mark.parametrize("name", ["简称PS4完全版", "简称PS5标准版"])
def test_conflicting_spec_goes_to_ai(name):
    calls = []
    item = parse(name, [entry(variant_id=2, platform="PS5", edition="完全版")],
                 lambda value: calls.append(value) or {"name_zh": "另一个建议"})
    assert item.match_status == "conflict"
    assert item.name_id is item.variant_id is None
    assert calls == [name]
    assert item.ai_suggestion.name_zh == "另一个建议"
    assert item.name_zh is None


def test_full_alias_before_stripped_alias():
    item = parse("简称完全版", [entry(), entry(variant_id=2, platform="PS5", edition="完全版").model_copy(update={"aliases": ["简称完全版"]})])
    assert item.variant_id == 2


def test_ambiguity_and_duplicate_targets():
    a = entry(variant_id=2, platform="PS5", edition="标准版")
    b = entry(variant_id=3, platform="PS4", edition="标准版")
    assert parse("简称", [a, b]).match_status == "ambiguous"
    assert parse("简称 PS4", [a, b]).variant_id == 3
    assert parse("简称", [a, a]).variant_id == 2


def test_cache_keeps_spec_context_across_notes():
    calls = []
    cache = CachedSuggestions(lambda name: calls.append(name) or {"name_zh": "标准游戏"})
    first = parse("简称完全版", suggest=cache)
    second = parse("简称完全版", suggest=cache)
    parse("简称豪华版", suggest=cache)
    assert calls == ["简称完全版", "简称豪华版"]
    assert cache.stats() == {"requests": 2, "cache_hits": 1, "failures": 0}
    assert first.ai_suggestion == second.ai_suggestion
    assert first.lowprice_cny == second.lowprice_cny == 265
    assert first.review_status == second.review_status == "pending"


def test_cache_failure_is_not_retried_or_leaked():
    def fail(_):
        raise RuntimeError("secret-server-response")
    cache = CachedSuggestions(fail)
    for _ in range(2):
        item = parse("未知", suggest=cache)
        assert "AI辅助失败" in item.issues
        assert "secret" not in item.model_dump_json()
    assert cache.stats() == {"requests": 1, "cache_hits": 1, "failures": 1}


@pytest.mark.parametrize("url", ["postgresql+psycopg://localhost/modou", "sqlite://", "postgresql+psycopg://localhost/modou_test?dbname=modou", "postgresql+psycopg://localhost/modou_test?options=bad"])
def test_production_and_override_urls_rejected_before_connect(url, monkeypatch):
    monkeypatch.setattr("modou.catalog_memory.create_engine", lambda *a, **k: pytest.fail("不应建立连接"))
    with pytest.raises(ValueError):
        read_test_catalog({"MODOU_TEST_DATABASE_URL": url})


def test_generic_database_url_ignored():
    assert guarded_url({"DATABASE_URL": "postgresql+psycopg://localhost/modou"}).database == "modou_test"


def test_config_bom_quotes_and_equals(workdir, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    path = workdir / "test.env"
    path.write_text('\ufeff# comment\nDEEPSEEK_API_KEY="fake=a=b"\n', encoding="utf-8")
    assert read_config(path)["DEEPSEEK_API_KEY"] == "fake=a=b"


def test_manifest_shared_cache_and_pending_output(workdir, monkeypatch):
    from modou.memory_cli import run
    monkeypatch.setattr("modou.memory_cli.read_test_catalog", lambda _: [entry()])
    calls = []
    monkeypatch.setattr("modou.memory_cli.DeepSeek", lambda **kwargs: lambda name: calls.append(name) or {"name_zh": "建议名"})
    (workdir / "note.txt").write_text("标题\n————实时新增————\n未知完全版｜🇭🇰265\n简称｜🇭🇰200", encoding="utf-8")
    manifest = workdir / "manifest.json"
    manifest.write_text(json.dumps([{"path": "note.txt", "date": "2026-11-03"}] * 2), encoding="utf-8")
    output = workdir / "out"
    summary = run(manifest, output, values={}, use_ai=True)
    assert calls == ["未知完全版"]
    assert summary["ai"] == {"requests": 1, "cache_hits": 1, "failures": 0}
    assert all(note["alias_hits"] == 1 for note in summary["notes"])
    assert json.loads((output / "note-1.json").read_text(encoding="utf-8"))["items"][0]["review_status"] == "pending"
    with pytest.raises(ValueError, match="拒绝覆盖"):
        run(manifest, output, values={}, use_ai=True)


def test_postgresql_alias_integration_rolls_back():
    """Only opt in explicitly; no migration, no schema creation, always rollback fixtures."""
    import os
    if os.environ.get("MODOU_MEMORY_PG_TEST") != "1":
        pytest.skip("需要显式启用modou_test专项集成验证")
    engine = create_engine(guarded_url(read_config()), connect_args={"connect_timeout": 8, "dbname": "modou_test"})
    tables = [GameName, GameVariant, GameAlias, PriceRecord, DataSource]
    try:
        with engine.connect() as conn:
            assert conn.scalar(text("select current_database()")) == "modou_test"
            before = [conn.scalar(select(func.count()).select_from(model)) for model in tables]
            conn.rollback()
            transaction = conn.begin()
            try:
                with Session(bind=conn, join_transaction_mode="rollback_only") as session:
                    game = GameName(name_zh="M02专项测试名", name_en="Memory Test")
                    session.add(game)
                    session.flush()
                    spec = GameVariant(name_id=game.name_id, platform="PS5", edition="完全版")
                    session.add(spec)
                    session.flush()
                    session.add_all([GameAlias(name_id=game.name_id, alias="M02测试简称"),
                                     GameAlias(name_id=game.name_id, variant_id=spec.variant_id, alias="M02测试简称完全版")])
                    session.flush()
                    catalog = [e for e in load_aliases(conn) if e.name_id == game.name_id]
                    assert parse("M02测试简称", catalog).variant_id is None
                    assert parse("M02测试简称完全版", catalog).variant_id == spec.variant_id
            finally:
                transaction.rollback()
            after = [conn.scalar(select(func.count()).select_from(model)) for model in tables]
            assert after == before
    finally:
        engine.dispose()
