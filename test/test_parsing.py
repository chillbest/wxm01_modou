import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from modou.deepseek import DeepSeek
from modou.parsing import CatalogEntry, ReviewItem, parse_note, read_note


def parse(line, section="实时新增", **kwargs):
    return parse_note(f"标题\n————{section}————\n{line}", **kwargs).items[0]


@pytest.mark.parametrize("tail,method", [("", ""), ("｜凑-50", "凑-50"), ("｜积-50", "积-50")])
def test_final_price(tail, method):
    item = parse("只狼｜🇭🇰203" + tail)
    assert item.lowprice_cny == Decimal("203")
    assert item.lowprice_method == method


def test_history_and_edition():
    item = parse("🔸羊蹄山之魂完全版｜🇭🇰265｜史低257", "福8-80区")
    assert item.edition == "完全版"
    assert item.notes == ["史低257"]
    assert item.lowprice_cny == 265
    assert item.lowprice_method == "福袋8折减80"


@pytest.mark.parametrize("flag,region", [("🇭🇰", "港版"), ("🇨🇳", "国行"), ("🇺🇳", "海外版"), ("🇪🇺", "欧版"), ("🇯🇵", "日版"), ("🇰🇷", "韩版"), ("🇺🇸", "美版"), ("🇹🇼", "台版")])
def test_regions(flag, region):
    assert parse(f"游戏｜{flag}100").region == region


@pytest.mark.parametrize("code,region", [("HK", "港版"), ("UN", "海外版"), ("EU", "欧版"),
                                         ("JP", "日版"), ("CN", "国行"), ("US", "美版"), ("KR", "韩版")])
@pytest.mark.parametrize("style", ["joined", "lowercase", "spaced_currency"])
def test_region_letter_codes(code, region, style):
    prefix = code.lower() if style == "lowercase" else code
    price = prefix + (" ￥265" if style == "spaced_currency" else "265")
    item = parse(f"游戏｜{price}")
    assert item.region == region
    assert item.lowprice_cny == 265


@pytest.mark.parametrize("prefix", ["GB", "HKG", "UNKNOWN", "UNEU"])
def test_unknown_region_not_guessed(prefix):
    item = parse(f"游戏｜{prefix}265")
    assert item.region is None
    assert "地区待确认" in item.issues


def test_sample_region_totals():
    from collections import Counter
    directory = Path(__file__).resolve().parents[1] / "Doc"
    regions = Counter(item.region for file in directory.glob("*.txt")
                      for item in parse_note(read_note(file)).items)
    assert regions == {"港版": 93, "日版": 18, "海外版": 27, "国行": 3, "美版": 1, "欧版": 8, "韩版": 2}


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "100/200", "100000000", "1.001"])
def test_invalid_price(amount):
    item = parse(f"游戏｜🇭🇰{amount}")
    assert item.lowprice_cny is None
    assert item.issues


def test_unknowns_and_digital_exclusion():
    result = parse_note("标题\n————实时新增————\n游戏｜🇬🇧100\n————数字折扣————\n游戏｜💰1")
    assert len(result.items) == 1
    item = result.items[0]
    assert item.platform is item.edition is item.region is item.lowprice_date is None
    assert result.skipped_lines == [5]
    assert "来源链接待补" in result.validation_errors


@pytest.mark.parametrize("name", ["只狼", "Sekiro", "狼"])
def test_catalog(name):
    entry = CatalogEntry(name_zh="只狼", name_en="Sekiro", aliases=["只狼", "Sekiro", "狼"])
    item = parse(f"{name} PS4标准版｜🇭🇰203", catalog=[entry], published_date=date(2026, 11, 3))
    assert item.name_zh == "只狼"
    assert item.platform == "PS4"
    assert item.edition == "标准版"
    assert not item.issues


def test_ambiguous_catalog():
    item = parse("狼｜🇭🇰203", catalog=[CatalogEntry(name_zh=n, aliases=["狼"]) for n in ["只狼", "另一游戏"]])
    assert item.name_zh is None
    assert "游戏名称匹配歧义" in item.issues


def test_ai_is_only_suggestion():
    item = parse("狼｜🇭🇰203", suggest=lambda _: {"name_zh": "只狼", "edition": "标准版"})
    assert item.ai_suggestion.name_zh == "只狼"
    assert item.name_zh is item.edition is None
    assert "AI建议待人工确认" in item.issues
    item = parse("狼｜🇭🇰203", suggest=lambda _: {"lowprice_cny": 1})
    assert "AI辅助失败" in item.issues
    assert item.lowprice_cny == 203


@pytest.mark.parametrize("content,finish", [(' ', 'stop'), ('{}', 'length'), ('{"price":1}', 'stop')])
def test_bad_ai_response(content, finish):
    def transport(request, timeout):
        assert request.full_url == "https://api.deepseek.com/chat/completions"
        assert timeout == 30
        return io.BytesIO(json.dumps({"choices": [{"finish_reason": finish, "message": {"content": content}}]}).encode())
    with pytest.raises(RuntimeError, match="格式无效"):
        DeepSeek("test-key", transport=transport)("狼")


def test_valid_ai_response():
    def transport(request, timeout):
        payload = json.loads(request.data)
        assert payload["response_format"] == {"type": "json_object"}
        return io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": '{"name_zh":"只狼","edition":null}'}}]}).encode())
    assert DeepSeek("test-key", transport=transport)("狼").name_zh == "只狼"


def test_pydantic_rejects_invalid_fields():
    with pytest.raises(ValidationError):
        ReviewItem(line_number=1, raw_line="", section="", raw_name="游戏", platform="Xbox")


def test_explicit_date_overrides_publication():
    assert parse("游戏｜🇭🇰100｜2026-11-01", published_date=date(2026, 11, 3)).lowprice_date == date(2026, 11, 1)
    assert parse("游戏｜🇭🇰100｜2026-02-30", published_date=date(2026, 11, 3)).lowprice_date is None


@pytest.mark.parametrize("filename,day,count", [("11.3｜Ps好价光盘.txt", 3, 49), ("11.7｜Ps好价光盘.txt", 7, 53), ("11.10｜Ps好价光盘.txt", 10, 50)])
def test_real_samples(filename, day, count):
    text = read_note(Path(__file__).resolve().parents[1] / "Doc" / filename)
    result = parse_note(text, published_date=date(2026, 11, day))
    assert len(result.items) == count
    assert all(i.lowprice_cny is not None and i.region is not None for i in result.items)
    assert all("数字折扣" not in i.section for i in result.items)
    assert all(i.platform is None for i in result.items)


@pytest.mark.parametrize("raw", ["Nba2k27", "nba2K27", "NBA2K27"])
def test_uppercase_before_identification_preserves_original(raw):
    seen = []
    item = parse(f"{raw}｜HK100", suggest=lambda name: seen.append(name) or {"name_zh": "NBA 2K27"})
    assert item.raw_name == raw
    assert item.normalized_name == "NBA2K27"
    assert seen == ["NBA2K27"]


def test_uppercase_alias_matching_and_dlc_suffix():
    entry = CatalogEntry(name_zh="测试游戏", aliases=["game"], name_id=1)
    item = parse("GaMe+dlc｜HK100", catalog=[entry])
    assert item.raw_name == "GaMe+dlc"
    assert item.normalized_name == "GAME+DLC"
    assert item.name_id == 1
    assert item.edition == "+dlc"


@pytest.mark.parametrize("section", ["实时新增", "未注明优惠的栏目"])
def test_missing_method_stays_empty(section):
    item = parse("游戏｜HK100", section=section)
    assert item.lowprice_method == ""
    assert "优惠方式待确认" not in item.issues
