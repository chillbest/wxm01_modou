"""M02: deterministic extraction; uncertain facts remain review issues."""
import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name_zh: str = Field(min_length=1)
    name_en: str | None = None
    aliases: list[str] = Field(default_factory=list)
    name_id: int | None = None
    variant_id: int | None = None
    platform: Literal["PS5", "PS4"] | None = None
    edition: str | None = None


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name_zh: str | None = None
    edition: str | None = None


class ReviewItem(BaseModel):
    line_number: int
    raw_line: str
    section: str
    raw_name: str
    normalized_name: str = ""
    name_id: int | None = None
    variant_id: int | None = None
    match_status: Literal["unmatched", "alias", "ambiguous", "conflict"] = "unmatched"
    review_status: Literal["pending"] = "pending"
    name_zh: str | None = None
    name_en: str | None = None
    platform: Literal["PS5", "PS4"] | None = None
    edition: str | None = None
    region: str | None = None
    lowprice_cny: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    lowprice_method: str | None = None
    lowprice_date: date | None = None
    notes: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    ai_suggestion: Suggestion | None = None


class ParsedNote(BaseModel):
    title: str
    source_text: str
    published_date: date | None
    source_url: str | None
    items: list[ReviewItem]
    validation_errors: list[str]
    skipped_lines: list[int]


REGIONS = {"🇨🇳": "国行", "🇭🇰": "港版", "🇹🇼": "台版", "🇯🇵": "日版",
           "🇰🇷": "韩版", "🇺🇸": "美版", "🇪🇺": "欧版", "🇺🇳": "海外版"}
REGION_CODES = {"HK": "港版", "UN": "海外版", "EU": "欧版", "JP": "日版",
                "CN": "国行", "US": "美版", "KR": "韩版"}
REGION_PREFIX = re.compile(r"^(HK|UN|EU|JP|CN|US|KR)(?=\s|[¥￥\d])", re.I)
EDITIONS = re.compile(r"(完全版|豪华版|年度版|标准版|\+dlc)$", re.I)


def read_note(path):
    data = path.read_bytes()
    return data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")


def normalize_name(name):
    return " ".join(name.split()).upper()


def match_alias(item, base_name, catalog):
    """Full source alias takes precedence; never infer a variant from its mere existence."""
    matches = []
    for candidate in [item.raw_name, base_name]:
        matches = [entry for entry in catalog if normalize_name(candidate) in
                   [normalize_name(alias) for alias in entry.aliases]]
        if matches:
            break
    if not matches:
        item.issues.append("游戏名称未匹配")
        return
    compatible = [entry for entry in matches if not (
        (item.platform and entry.platform and item.platform != entry.platform) or
        (item.edition and entry.edition and item.edition.casefold() != entry.edition.casefold()))]
    if not compatible:
        item.match_status = "conflict"
        item.issues.append("原文规格与别名记忆冲突")
        return
    # Multiple aliases pointing to the same target are one identification.
    targets = {(entry.name_id, entry.name_zh, entry.variant_id, entry.platform, entry.edition): entry
               for entry in compatible}
    if len(targets) != 1:
        item.match_status = "ambiguous"
        item.issues.append("游戏名称匹配歧义")
        return
    entry = next(iter(targets.values()))
    item.match_status = "alias"
    item.name_id, item.name_zh, item.name_en = entry.name_id, entry.name_zh, entry.name_en
    if entry.variant_id is not None:
        item.variant_id = entry.variant_id
        item.platform, item.edition = entry.platform, entry.edition


def parse_note(text: str, *, published_date: date | None = None,
               source_url: str | None = None, catalog: list[CatalogEntry] = (),
               suggest=None) -> ParsedNote:
    lines = text.splitlines()
    items, skipped, errors = [], [], []
    section = ""
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if "——" in line:
            section = line
            continue
        if "数字折扣" in section:
            if line:
                skipped.append(number)
            continue
        if "｜" not in line or number == 1:
            if line.startswith(("🔸", "🔹")):
                errors.append(f"第{number}行：报价格式无法识别")
            continue
        parts = line.split("｜")
        name = parts[0].lstrip("🔸🔹▪️ ").strip()
        item = ReviewItem(line_number=number, raw_line=raw, section=section,
                          raw_name=name, normalized_name=normalize_name(name),
                          lowprice_date=published_date, lowprice_method="")
        name = item.normalized_name
        platform = re.search(r"(?<![A-Za-z0-9])(PS5|PS4)(?![A-Za-z0-9])", name, re.I)
        if platform:
            item.platform = platform[1].upper()
            name = (name[:platform.start()] + name[platform.end():]).strip()
        edition = EDITIONS.search(name)
        if edition:
            item.edition = edition[1].lower() if edition[1].lower() == "+dlc" else edition[1]
            name = name[:edition.start()].strip()
        match_alias(item, name, catalog)
        if item.match_status != "alias":
            if suggest:
                try:
                    item.ai_suggestion = Suggestion.model_validate(suggest(item.normalized_name))
                    item.issues.append("AI建议待人工确认")
                except Exception:
                    item.issues.append("AI辅助失败")
        price_text = parts[1].strip()
        for flag, region in REGIONS.items():
            if price_text.startswith(flag):
                item.region = region
                price_text = price_text[len(flag):].strip()
                break
        if item.region is None:
            code = REGION_PREFIX.match(price_text)
            if code:
                item.region = REGION_CODES[code[1].upper()]
                price_text = price_text[code.end():].strip()
        if re.fullmatch(r"(?:¥|￥)?\d+(?:\.\d{1,2})?", price_text):
            value = Decimal(price_text.lstrip("¥￥"))
            if 0 < value < Decimal("100000000"):
                item.lowprice_cny = value
            else:
                item.issues.append("金额超出有效范围")
        else:
            item.issues.append("金额格式无法识别")
        if "福8-80" in section or "福袋8折减80" in section:
            item.lowprice_method = "福袋8折减80"
        elif "积/v3" in section:
            item.lowprice_method = "积/v3"
        for note in parts[2:]:
            note = note.split("#", 1)[0].strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", note):
                try:
                    item.lowprice_date = date.fromisoformat(note)
                except ValueError:
                    item.lowprice_date = None
                    item.issues.append("正文日期无效")
                item.notes.append(note)
            elif re.fullmatch(r"(?:凑|积)-\d+", note):
                item.lowprice_method = note
            elif note:
                item.notes.append(note)
                if not re.fullmatch(r"史低\d+(?:\.\d{1,2})?", note):
                    item.issues.append("未识别的行尾说明")
        for field, label in [(item.region, "地区"), (item.platform, "平台"),
                             (item.edition, "版本"), (item.lowprice_date, "日期"),
                             (item.lowprice_method, "优惠方式")]:
            if field is None:
                item.issues.append(f"{label}待确认")
        items.append(item)
    if not source_url:
        errors.append("来源链接待补")
    elif not re.fullmatch(r"https://(?:www\.)?xiaohongshu\.com/[^\s]+|https://xhslink\.com/[^\s]+", source_url):
        errors.append("来源链接格式待确认")
    if not published_date:
        errors.append("发布日期待确认")
    if not items:
        errors.append("未识别到实体光盘报价")
    return ParsedNote(title=lines[0] if lines else "", source_text=text, published_date=published_date,
                      source_url=source_url, items=items, validation_errors=errors,
                      skipped_lines=skipped)
