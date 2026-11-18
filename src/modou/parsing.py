"""M02: deterministic extraction; uncertain facts remain review issues."""
from .logging_setup import note_total, event, context, stage, summary, failure_reason
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
    gpc_id: int | None = None
    platform: str | None = None
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
    gpc_id: int | None = None
    match_status: Literal["unmatched", "alias", "ambiguous", "conflict"] = "unmatched"
    review_status: Literal["pending"] = "pending"
    name_zh: str | None = None
    name_en: str | None = None
    platform: str | None = None
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
    targets = {(entry.gpc_id, entry.name_zh): entry for entry in matches}
    if len(targets) != 1:
        item.match_status = "ambiguous"
        item.issues.append("游戏名称匹配歧义")
        return
    entry = next(iter(targets.values()))
    item.match_status = "alias"
    item.gpc_id, item.name_zh, item.name_en = entry.gpc_id, entry.name_zh, entry.name_en


def parse_note(text: str, *, published_date: date | None = None,
               source_url: str | None = None, catalog: list[CatalogEntry] = (),
               suggest=None, log_results=True, note_id="-") -> ParsedNote:
    lines = text.splitlines()
    count, count_section = 0, ''
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if '——' in line:
            count_section = line
        elif '数字折扣' not in count_section and '｜' in line and number != 1:
            count += 1
    note_total(count)
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
                if log_results:
                    event("报价行无法解析", note_id=str(note_id), line=number, reason="缺少报价分隔符")
            continue
        parts = line.split("｜")
        name = parts[0].lstrip("🔸🔹▪️ ").strip()
        item = ReviewItem(line_number=number, raw_line=raw, section=section,
                          raw_name=name, normalized_name=normalize_name(name),
                          lowprice_date=published_date, lowprice_method="直接购买", platform="PS5")
        name = item.normalized_name
        platform = re.search(r"(?<![A-Za-z0-9])(PS5|PS4)(?![A-Za-z0-9])", name, re.I)
        if platform:
            item.platform = platform[1].upper()
            name = (name[:platform.start()] + name[platform.end():]).strip()
        edition = EDITIONS.search(name)
        if edition:
            item.edition = edition[1].lower() if edition[1].lower() == "+dlc" else edition[1]
            name = name[:edition.start()].strip()
        # Do not discard content edition when identifying a GPC.
        match_alias(item, re.sub(r"\s*(?<![A-Za-z0-9])(PS5|PS4)(?![A-Za-z0-9])\s*", "", item.normalized_name).strip(), catalog)
        if item.match_status != "alias":
            if suggest:
                try:
                    item.ai_suggestion = Suggestion.model_validate(suggest(item.normalized_name))
                    item.issues.append("AI建议待人工确认")
                except Exception as exc:
                    if log_results:
                        with context(note_id=str(note_id), line=number, raw_name=item.raw_name):
                            event("AI辅助失败原因", reason=failure_reason(exc))
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
        if log_results:
            with context(note_id=str(note_id), line=number, raw_name=item.raw_name):
                stage('本地别名', [{'name_zh': item.name_zh, 'gpc_id': item.gpc_id}] if item.match_status == 'alias' else (), result={'alias': '命中', 'ambiguous': '歧义', 'unmatched': '未命中', 'conflict': '冲突'}[item.match_status],
                      reason='唯一别名命中' if item.match_status == 'alias' else '多个别名目标' if item.match_status == 'ambiguous' else '无匹配别名')
                for unused in ('Bangumi本地资料', 'BangumiAPI'):
                    stage(unused, result='未执行', reason='该入口不使用Bangumi')
                stage('DeepSeek', [{'name_zh': item.ai_suggestion.name_zh}] if item.ai_suggestion and item.ai_suggestion.name_zh else (), result='AI建议' if item.ai_suggestion and item.ai_suggestion.name_zh else '调用失败' if 'AI辅助失败' in item.issues else '未命中' if suggest and item.match_status != 'alias' else '未执行',
                      reason='建议待人工确认' if item.ai_suggestion and item.ai_suggestion.name_zh else 'AI辅助失败' if 'AI辅助失败' in item.issues else 'AI未给出名称' if suggest and item.match_status != 'alias' else '别名已命中或未启用AI')
                event('条目最终结果', result='已识别' if item.match_status == 'alias' or item.ai_suggestion and item.ai_suggestion.name_zh else '歧义' if item.match_status == 'ambiguous' else '未识别', reason='；'.join(item.issues), review_status='pending')
        items.append(item)
    if not source_url:
        errors.append("来源链接待补")
    elif not re.fullmatch(r"https://(?:www\.)?xiaohongshu\.com/[^\s]+|https://xhslink\.com/[^\s]+", source_url):
        errors.append("来源链接格式待确认")
    if not published_date:
        errors.append("发布日期待确认")
    if not items:
        errors.append("未识别到实体光盘报价")
    if log_results:
        with context(note_id=str(note_id)):
            summary(["已识别" if i.match_status == "alias" or i.ai_suggestion and i.ai_suggestion.name_zh else "歧义" if i.match_status == "ambiguous" else "未识别" for i in items])
    return ParsedNote(title=lines[0] if lines else "", source_text=text, published_date=published_date,
                      source_url=source_url, items=items, validation_errors=errors,
                      skipped_lines=skipped)
