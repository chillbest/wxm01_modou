"""Known-host URL resolution and recorded AI main-subject suggestions."""
import json
import re
from html import unescape
from urllib.request import Request
from urllib.parse import urljoin
from ..http_transport import direct_opener
from ..bangumi import AnonymousAPI, valid_gamefaqs_link
from ..bangumi_cli import ai_client


def valid_vgcollect_link(url):
    return bool(re.fullmatch(r'https://vgcollect\.com/item/[0-9]+/?', url))


class VGCollectRedirect(__import__('urllib.request', fromlist=['HTTPRedirectHandler']).HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        if not valid_vgcollect_link(target):
            raise ValueError('VGCollect跳转目标不是可信产品页')
        return super().redirect_request(req, fp, code, msg, headers, target)


def vgcollect(url):
    if not valid_vgcollect_link(url):
        raise ValueError('VGCollect产品URL无效')
    try:
        with direct_opener(VGCollectRedirect).open(Request(url, headers={'User-Agent': 'Mozilla/5.0 Modou/0.1'}), timeout=20) as response:
            body = response.read(2_000_001)
            if not valid_vgcollect_link(response.geturl()):
                raise ValueError('VGCollect返回无效产品URL')
    except (OSError, TimeoutError) as exc:
        raise ValueError('VGCollect资料请求失败，链接未保存；请稍后重试') from exc
    if len(body) > 2_000_000:
        raise ValueError('VGCollect产品页面过大')
    html = body.decode('utf-8', errors='replace')
    title = re.search(r'<title\b[^>]*>(.*?)</title>', html, re.S | re.I)
    if not title:
        raise ValueError('未取得VGCollect产品名称，链接未保存')
    text = unescape(re.sub('<[^>]+>', '', title[1])).strip()
    match = re.fullmatch(r'(.+)\s+-\s+.+?\s+-\s+VGCollect', text, re.I)
    from ..bangumi import english_name
    name = english_name({'name': match[1].strip()}) if match else None
    if not name:
        raise ValueError('未取得VGCollect英文产品名，链接未保存')
    return name


def subject(url, api=None):
    match = re.fullmatch(r'https://(?:bgm\.tv|bangumi\.tv|chii\.in)/subject/([0-9]+)/?', url)
    if not match:
        raise ValueError('请填写Bangumi Subject URL')
    data = (api or AnonymousAPI()).request('/v0/subjects/' + match[1])
    if data.get('type') != 4:
        raise ValueError('Bangumi条目不是游戏')
    return data


class NoRedirect(__import__('urllib.request', fromlist=['HTTPRedirectHandler']).HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        if not valid_gamefaqs_link(target):
            raise ValueError('GameFAQs跳转目标不是可信产品页，链接未保存')
        return super().redirect_request(req, fp, code, msg, headers, target)


def gamefaqs(url):
    if not valid_gamefaqs_link(url):
        raise ValueError('GameFAQs产品URL无效')
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0 Modou/0.1'})
    with direct_opener(NoRedirect).open(req, timeout=20) as response:
        body = response.read(2_000_001)
        canonical = response.geturl() if hasattr(response, 'geturl') else url
    if not valid_gamefaqs_link(canonical):
        raise ValueError('未取得有效GameFAQs产品URL')
    if len(body) > 2_000_000:
        raise ValueError('产品页面过大')
    html = body.decode('utf-8', errors='replace')
    title = re.search(r'<title[^>]*>(.*?)</title>', html, re.S | re.I)
    if not title:
        raise ValueError('未取得GameFAQs产品名称')
    page_title = unescape(re.sub('<[^>]+>', '', title[1])).strip()
    if re.search(r'access denied|just a moment|captcha|attention required', page_title, re.I):
        raise ValueError('GameFAQs返回访问验证页面，未取得产品名称')
    heading = re.search(r'<h1\b[^>]*>(.*?)</h1>', html, re.S | re.I)
    name = unescape(re.sub('<[^>]+>', '', heading[1] if heading else title[1])).strip()
    name = re.sub(r'\s*[-|]\s*GameFAQs\b.*$', '', name, flags=re.I)
    name = re.sub(r'\s+(?:for|on)\s+(?:PlayStation\s*[45]|PS[45]|PC|Xbox\b.*|Nintendo\b.*).*$', '', name, flags=re.I).strip()
    from ..bangumi import english_name
    english = english_name({'name': name})
    if not english:
        raise ValueError('GameFAQs未提供可确认的英文产品名，链接未保存')
    platform = {'ps5': 'PS5', 'ps4': 'PS4'}.get(canonical.split('/')[3])
    return {'name': english, 'name_en': english, 'name_zh': english, 'outlink': canonical,
            'platforms': [platform] if platform else [], 'page_title': page_title}


def suggest_main(candidate, values, api=None, suggest=None):
    # Deprecated 2026-11-19 (6d8b20f4): retain implementation as comments.
    return {'status': 'disabled', 'main_id': None, 'source': 'deepseek_gamefaqs', 'interactions': [],
            'reason': 'GameFAQs主版本AI识别已弃用'}
    #     client = None
    #     before = 0
    #     result = {'status': 'unknown', 'main_id': None, 'source': 'deepseek_gamefaqs'}
    #     try:
    #         client = suggest or ai_client(values)
    #         before = len(client.interactions)
    #         answer = client({'task': 'main_subject', 'raw_name': candidate.get('name_zh') or candidate.get('name'),
    #                          'note': json.dumps(candidate, ensure_ascii=False), 'candidates': {}})
    #         sid = answer.get('main_subject_id')
    #         if type(sid) is int:
    #             sid = str(sid)
    #         if not isinstance(sid, str) or not re.fullmatch('[0-9]+', sid):
    #             raise ValueError('DeepSeek未确定主版本')
    #         detail = subject('https://bgm.tv/subject/' + sid, api)
    #         result.update(status='suggested', main_id=sid, reason=answer.get('reason'), subject=detail)
    #     except Exception as exc:
    #         result.update(status='failed', reason=str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
    #     records = [dict(r, stage='GameFAQs主版本') for r in (client.interactions[before:] if client is not None else [])]
    #     result['interactions'] = records
    #     return result
