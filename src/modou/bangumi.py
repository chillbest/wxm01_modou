"""Anonymous Bangumi candidates; never writes business data."""
from .logging_setup import event, stage as log_stage, context, failure_reason, logged_request
import json
import re
import unicodedata
import zipfile
from pathlib import Path
from urllib.request import Request
from .http_transport import bangumi_urlopen


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def latest_dump(directory):
    files = []
    for path in Path(directory).glob('*.zip'):
        match = re.search(r'(\d{4}-\d{2}-\d{2})(?:[.T_-](\d{6})Z?)?', path.name)
        if match:
            files.append((match.group(1), match.group(2) or '', path.name, path))
    if not files:
        raise ValueError('没有带日期的Bangumi ZIP')
    return max(files)[-1]


def names(subject):
    result = [subject.get('name', ''), subject.get('name_cn', '')]
    info = subject.get('infobox', [])
    if isinstance(info, str):
        # Dump stores raw wiki infobox, API stores structured values.
        result += re.findall(r'\[([^\[\]\r\n]+)\]', info)
        result += re.findall(r'^\|(?:中文名|别名|英文名)\s*=\s*([^\r\n{]+)', info, re.M)
    else:
        for field in info:
            if field.get('key') in ('别名', '中文名', '英文名'):
                value = field.get('value')
                if isinstance(value, str):
                    result.append(value)
                elif isinstance(value, list):
                    result += [v['v'] for v in value if isinstance(v, dict) and isinstance(v.get('v'), str)]
    return {normalized(n) for n in result if n}


def english_name(candidate):
    """Prefer English aliases; only accept Latin titles without other scripts."""
    def acceptable(value):
        if not isinstance(value, str):
            return None
        value = value.strip()
        has_letter = False
        latin_base = False
        for char in unicodedata.normalize('NFD', value):
            category = unicodedata.category(char)
            if category.startswith('L'):
                if 'LATIN' not in unicodedata.name(char, ''):
                    return None
                has_letter = latin_base = True
            elif category.startswith('M'):
                if not latin_base:
                    return None
            elif category.startswith(('N', 'P', 'S')) or char.isspace():
                latin_base = False
            else:
                return None
        return value if has_letter else None
    if candidate.get('gpc_id') and candidate.get('name_en'):
        return candidate['name_en']
    info = candidate.get('infobox') or []
    aliases = []
    if isinstance(info, list):
        for field in info:
            key, value = field.get('key'), field.get('value')
            if key in ('英文名', '英文', 'English'):
                found = acceptable(value)
                if found:
                    return found
            if key == '别名':
                aliases.extend(value if isinstance(value, list) else [value])
    elif isinstance(info, str):
        for key, value in re.findall(r'^\|([^=\n]+)=(.*?)(?=^\||^\}\}|\Z)', info, re.M | re.S):
            if key.strip() in ('英文名', '英文', 'English') and acceptable(value):
                return acceptable(value)
            if key.strip() == '别名':
                aliases.extend(re.findall(r'\[([^\[\]\n]+)\]', value) or [value.strip()])
    unmarked = []
    for alias in aliases:
        if isinstance(alias, dict):
            label, value = str(alias.get('k', '')), alias.get('v')
        else:
            label, value = '', alias
            if isinstance(value, str) and '|' in value:
                label, value = value.split('|', 1)
        found = acceptable(value)
        if not found:
            continue
        if label.strip().lower() in ('英文', '英语', '英文名', 'english', 'en'):
            return found
        if not label.strip():
            unmarked.append(found)
    if unmarked:
        return unmarked[0]
    return acceptable(candidate.get('name'))


class LocalDump:
    """Single streaming pass per batch, avoiding extraction of the ~1GB subject file."""
    def __init__(self, directory):
        self.path = latest_dump(directory)

    def lookup_many(self, queries):
        wanted = {normalized(q) for q in queries}
        result = {q: [] for q in wanted}
        with zipfile.ZipFile(self.path) as archive, archive.open('subject.jsonlines') as stream:
            for line in stream:
                item = json.loads(line)
                if item.get('type') == 4 and item.get('platform') == 4001:
                    for key in names(item) & wanted:
                        result[key].append(item)
        return result


class AnonymousAPI:
    def __init__(self, transport=bangumi_urlopen):
        self.transport = transport
        self.cache = {}

    @logged_request("Bangumi（含缓存读取）")
    def request(self, path, payload=None):
        key = (path, json.dumps(payload, sort_keys=True))
        if key not in self.cache:
            request = Request('https://api.bgm.tv' + path,
                              data=json.dumps(payload).encode() if payload is not None else None,
                              headers={'User-Agent': 'ModouPhase1/0.1 (Bangumi game identification)',
                                       'Accept': 'application/json', 'Content-Type': 'application/json'})
            # No Authorization, cookies or credential configuration, including on retries.
            with self.transport(request, timeout=20) as response:
                self.cache[key] = json.load(response)
        return self.cache[key]

    def search(self, query):
        data = self.request('/v0/search/subjects?limit=10&offset=0',
                            {'keyword': query, 'sort': 'match', 'filter': {'type': [4]}})
        candidates = []
        for row in data['data']:
            if row.get('type') != 4:
                continue
            item = self.request('/v0/subjects/' + str(row['id']))
            if item.get('type') == 4 and item.get('platform') == '游戏':
                candidates.append(item)
        return candidates


def ps_platforms(candidate):
    """Collect explicit PS4/PS5 evidence for this exact game/version only."""
    info = candidate.get('infobox', [])
    values = []
    if isinstance(info, list):
        values = [field.get('value') for field in info if field.get('key') == '平台']
    elif isinstance(info, str):
        values = re.findall(r'^\|平台\s*=(.*?)(?=^\||^\}\}|\Z)', info, re.M | re.S)
    values += [candidate.get('platform'), candidate.get('platforms')]
    link = candidate.get('outlink')
    if valid_gamefaqs_link(link) and link.split('/')[3] in ('ps4', 'ps5'):
        values.append(link.split('/')[3])
    text = json.dumps(values, ensure_ascii=False).upper()
    return {'PS' + n for n in re.findall(r'(?<![A-Z0-9])(?:PS\s*|PLAYSTATION\s*)([45])(?![A-Z0-9])', text)}


def supports_ps_disc(candidate):
    return bool(ps_platforms(candidate))


def ai_candidate(candidate):
    """Complete infobox fields only; preserve order, duplicates and complex values."""
    info = candidate.get('infobox', [])
    if isinstance(info, list):
        fields = [(f['key'], f.get('value', '')) for f in info]
    else:
        fields = re.findall(r'^\|([^=\n]+)=(.*?)(?=^\||^\}\}|\Z)', info, re.M | re.S)
        fields = [(k.strip(), v.strip()) for k, v in fields]
        if not fields:
            fields = [('原始资料', info)]
    def value_text(value):
        if isinstance(value, list):
            value = [v['v'] if isinstance(v, dict) and set(v) == {'v'} else v for v in value]
        if isinstance(value, str) and value.startswith('{') and value.endswith('}'):
            matches = re.findall(r'^\[([^\n]*)\]$', value[1:-1].strip(), re.M)
            if matches and ''.join(value[1:-1].split()) == ''.join(('['+v+']') for v in matches).replace(' ', ''):
                value = matches
        text = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        if isinstance(value, str) and value and not any(c in value for c in '\r\n｜=\\"'):
            text = value
        return text.replace('｜', r'\uFF5C')
    return '｜'.join(value_text(k) + '=' + value_text(v) for k, v in fields)


def ai_candidate_line(candidate, label):
    """Selected complete fields; no per-candidate truncation."""
    keys = ('别名', '平台', '游戏类型', '发行日期')
    info = candidate.get('infobox') or []
    if isinstance(info, str):
        fields = re.findall(r'^\|([^=\n]+)=(.*?)(?=^\||^\}\}|\Z)', info, re.M | re.S)
        values = {k.strip(): v.strip() for k, v in fields}
    else:
        values = {f['key']: f.get('value') for f in info if f.get('key') in keys}
    return {'name': candidate.get('name'), 'name_cn': candidate.get('name_cn'),
            'infobox': {k: values.get(k) for k in keys}}


def valid_product_link(value):
    from urllib.parse import urlsplit
    if not isinstance(value, str) or re.search(r'[\s\x00-\x1f\x7f\\]', value):
        return False
    try:
        parsed = urlsplit(value)
        return bool(parsed.scheme in ('http', 'https') and parsed.hostname
                    and parsed.username is None and parsed.password is None
                    and (parsed.port is None or 0 < parsed.port <= 65535))
    except ValueError:
        return False


def valid_gamefaqs_link(value):
    """Accept only canonical HTTPS product roots, never search/category URLs."""
    import re
    return isinstance(value, str) and re.fullmatch(
        r'https://gamefaqs\.gamespot\.com/[a-z0-9-]+/[0-9]+-[a-z0-9]+(?:-[a-z0-9]+)*', value) is not None


def resolve(raw_name, note, aliases, local_candidates, api, suggest=None, *, note_id="-", line_number="-", ps_disc=False, defer_ai=False):
    with context(note_id=str(note_id), line=line_number, raw_name=raw_name):
        return _resolve(raw_name, note, aliases, local_candidates, api, suggest, ps_disc, defer_ai=defer_ai)


def _resolve(raw_name, note, aliases, local_candidates, api, suggest=None, ps_disc=False, preliminary=None, defer_ai=False):
    trace = []
    def eligible(candidates, name):
        candidates = list(candidates)
        kept = [c for c in candidates if c.get('gpc_id') == -1 or supports_ps_disc(c)] if ps_disc else candidates
        if len(kept) != len(candidates):
            event('候选平台过滤', stage=name, removed=len(candidates)-len(kept), remaining=len(kept), reason='PS光盘标题要求明确PS4或PS5平台；缺失资料也剔除')
        return kept
    def stage(name, candidates=(), **kwargs):
        candidates = list(candidates)
        trace.append({'candidates': [{k: c.get(k) for k in ('name_zh','name_cn','name','gpc_id','id','bangumi_id','outlink','edition','platforms','date') if c.get(k) is not None} for c in candidates], 'stage': name, 'result': kwargs.get('result') or ('命中' if len(candidates) == 1 else '歧义' if candidates else '未命中'), 'reason': kwargs.get('reason') or ('唯一候选' if len(candidates) == 1 else '多个候选' if candidates else '无匹配候选')})
        log_stage(name, candidates, **kwargs)
    blocked = next((c for c in aliases if c.get('gpc_id') == -1 and normalized(c['alias']) == normalized(raw_name)), None)
    blocked = blocked or ((preliminary or {}).get('stage_hits') or {}).get('alias')
    if blocked and blocked.get('gpc_id') == -1:
        stage('本地别名', [blocked], result='黑名单', reason='停止后续解析，视作已入库')
        return {'raw_name': raw_name, 'note': note, 'source': 'alias', 'candidates': [blocked],
                'ai_interactions': [], 'suggestion': None, 'gamefaqs_suggestion': None,
                'errors': [], 'stage_hits': {'alias': blocked}, 'stage_trace': trace,
                'status': 'pending', 'ps_disc_filter': ps_disc, 'blacklisted': True}
    if preliminary is not None:
        candidates = preliminary['candidates']
        source, errors = preliminary['source'], list(preliminary['errors'])
        stage_hits = dict(preliminary['stage_hits'])
        trace.extend(t for t in preliminary['stage_trace'] if t['stage'] not in ('DeepSeek', 'GameFAQs'))
    else:
        candidates = [dict(c) for c in aliases if normalized(c['alias']) == normalized(raw_name)]
        blocked = [c for c in candidates if c.get('gpc_id') == -1]
        candidates = blocked or eligible(candidates, '本地别名')
        stage('本地别名', list({c['gpc_id']: c for c in candidates}.values()))
        source, errors = 'alias', []
        stage_hits = {}
        if len({c['gpc_id'] for c in candidates}) == 1:
            stage_hits['alias'] = candidates[0]
        if len({c['gpc_id'] for c in candidates}) != 1:
            source = 'local'
            candidates = [dict(c, _ai_source='BGM本地') for c in eligible(local_candidates, 'Bangumi本地资料')]
            stage('Bangumi本地资料', candidates)
            if len(candidates) == 1:
                stage_hits['local'] = candidates[0]
            if len(candidates) != 1 or ps_disc:
                was_unique = len(candidates) == 1
                if not was_unique:
                    source = 'api'
                try:
                    online = [dict(c, _ai_source='BGM-API') for c in eligible(api.search(raw_name), 'BangumiAPI')]
                    stage('BangumiAPI', online)
                    candidates = list({str(c['id']): c for c in candidates + online}.values())
                    if len(candidates) != 1:
                        stage_hits.pop('local', None)
                        source = 'api'
                    elif online and not was_unique:
                        stage_hits['api'] = online[0]
                except Exception as exc:
                    stage('BangumiAPI', result='调用失败', reason=failure_reason(exc))
                    errors.append('Bangumi匿名API失败，保留本地候选并待人工审核')
        if source == 'alias':
            stage('Bangumi本地资料', result='未执行', reason='本地别名唯一命中')
        if source != 'api' and not any(t['stage'] == 'BangumiAPI' for t in trace):
            stage('BangumiAPI', result='未执行', reason='前序阶段唯一命中')
    if defer_ai:
        return {'raw_name': raw_name, 'note': note, 'source': source, 'candidates': candidates,
                'errors': errors, 'stage_hits': stage_hits, 'stage_trace': trace, 'status': 'pending',
                'ai_interactions': [], 'suggestion': None, 'gamefaqs_suggestion': None, 'ps_disc_filter': ps_disc}
    interactions = []
    counts, candidate_map, candidate_lines = {}, {}, {}
    for c in candidates:
        origin = c.get('_ai_source', 'BGM本地')
        counts[origin] = counts.get(origin, 0) + 1
        label = f'{origin}_候选{counts[origin]}'
        candidate_map[label] = c
        candidate_lines[label] = ai_candidate_line(c, label)
    def ask(payload, stage_name):
        collector = getattr(suggest, 'interactions', None)
        start = len(collector) if collector is not None else 0
        try:
            return suggest(payload)
        finally:
            if collector is not None:
                interactions.extend(dict(record, stage=stage_name) for record in collector[start:])
    suggestion = None
    if suggest and not stage_hits:
        try:
            suggestion = ask({'raw_name': raw_name, 'note': note, 'candidates': candidate_lines, **({'required_platforms': ['PS4', 'PS5']} if ps_disc else {})}, 'DeepSeek')
            if 'candidate' in suggestion:
                label = suggestion['candidate']
                if label is not None and (not isinstance(label, str) or label not in candidate_map):
                    raise ValueError('无效候选标识')
                suggestion = dict(suggestion, bangumi_id=candidate_map[label]['id'] if label is not None else None)
            allowed = {str(c['id']) for c in candidates}
            if suggestion.get('bangumi_id') is not None and str(suggestion['bangumi_id']) not in allowed:
                raise ValueError('AI选择不在候选中')
            if suggestion.get('bangumi_id') is not None:
                stage_hits['ds'] = next(c for c in candidates if str(c['id']) == str(suggestion['bangumi_id']))
                stage('DeepSeek', [stage_hits['ds']], result='AI建议', reason='从候选中选择，待人工确认')
            else:
                stage('DeepSeek', result='未命中', reason='AI未选择候选')
        except Exception as exc:
            stage('DeepSeek', result='调用失败', reason=failure_reason(exc))
            suggestion = None
            errors.append('DeepSeek辅助失败或选择无效')
    else:
        stage('DeepSeek', result='未执行', reason='前序阶段唯一命中，命中即停止' if stage_hits else '未启用AI')
    gamefaqs = None
    # Deprecated 2026-11-19 (6d8b20f4): GameFAQs automatic AI identification.
    #     if not stage_hits and suggest:
    #         try:
    #             proposed = ask({'task': 'gamefaqs', 'raw_name': raw_name, 'note': note,
    #                                 'candidates': candidate_lines, 'bangumi_suggestion': {k:v for k,v in suggestion.items() if k != 'bangumi_id'} if suggestion else None, **({'required_platforms': ['PS4', 'PS5']} if ps_disc else {})}, 'GameFAQs')
    #             link = proposed.get('outlink')
    #             if link is not None:
    #                 if not valid_gamefaqs_link(link) or not isinstance(proposed.get('name_zh'), str) or not proposed['name_zh'].strip():
    #                     raise ValueError('GameFAQs链接或名称无效')
    #                 if ps_disc and not supports_ps_disc({'outlink': link}):
    #                     stage('GameFAQs', result='未命中', reason='产品链接不是PS4或PS5，已剔除')
    #                 else:
    #                     gamefaqs = {k: proposed.get(k) for k in ('name_zh', 'name_en', 'outlink', 'reason', 'platforms')}
    #                     stage_hits['gamefaqs'] = gamefaqs
    #                     stage('GameFAQs', [gamefaqs], result='AI建议', reason='链接未经事实核验，待人工确认')
    #             else:
    #                 stage('GameFAQs', result='未命中', reason='AI未提供产品链接')
    #         except Exception as exc:
    #             stage('GameFAQs', result='调用失败', reason=failure_reason(exc))
    #             errors.append('GameFAQs辅助失败或链接无效')
    #     else:
    #         stage('GameFAQs', result='未执行', reason='前序阶段唯一命中，命中即停止' if stage_hits else '未启用AI')
    stage('GameFAQs', result='未执行', reason='功能已弃用：不再自动提供GameFAQs链接')
    identified = bool(stage_hits)
    event('条目最终结果', result='已识别' if identified else '歧义' if candidates else '未识别', reason='候选识别完成，待人工审核' if identified else '多个候选无法确定' if candidates else '无候选；' + '；'.join(errors), review_status='pending')
    return {'raw_name': raw_name, 'note': note, 'source': source, 'candidates': candidates,
            'ai_interactions': interactions, 'suggestion': suggestion, 'gamefaqs_suggestion': gamefaqs, 'errors': errors, 'stage_hits': stage_hits, 'stage_trace': trace, 'status': 'pending', 'ps_disc_filter': ps_disc}
