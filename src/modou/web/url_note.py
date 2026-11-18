"""Fetch public note text without credentials or executing page scripts."""
import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request
from ..http_transport import direct_opener


def check_url(url):
    try:
        p = urlsplit(url)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.port not in (None, 80, 443):
            raise ValueError('请输入公开HTTP或HTTPS笔记URL')
        addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('URL仅允许公开互联网地址')
    except (OSError, ValueError) as exc:
        raise ValueError('笔记URL无效或不是可访问的公开地址') from exc


class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class NoteHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.title, self.scripts = [], [], []
        self.skip = 0
        self.in_title = False
        self.script = None
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        if tag == 'script':
            self.script = []
        if tag == 'title':
            self.in_title = True
        if tag in ('p', 'div', 'br', 'li', 'article', 'h1', 'h2'):
            self.text.append('\n')
    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            self.scripts.append(''.join(self.script))
            self.script = None
        if tag in ('script', 'style', 'noscript'):
            self.skip = max(0, self.skip - 1)
        if tag == 'title':
            self.in_title = False
        if tag in ('p', 'div', 'li', 'article', 'h1', 'h2'):
            self.text.append('\n')
    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)
        elif self.in_title:
            self.title.append(data)
        elif not self.skip:
            self.text.append(data)


def extract_note(html):
    parser = NoteHTML()
    parser.feed(html)
    title = ''.join(parser.title).strip() or 'URL笔记'
    bodies = []
    def walk(value):
        if isinstance(value, dict):
            for key in ('articleBody', 'desc'):
                if isinstance(value.get(key), str) and value[key].strip():
                    bodies.append((value.get('title') or title, value[key]))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for script in parser.scripts:
        source = script.split('__INITIAL_STATE__=', 1)[-1].strip()
        if not source.startswith(('{', '[')):
            continue
        try:
            # XHS serializes undefined in its initial-state object; never eval JS.
            source = re.sub(r'(?<=:)undefined(?=[,}])', 'null', source)
            value, _ = json.JSONDecoder().raw_decode(source)
            walk(value)
        except (ValueError, RecursionError):
            continue
    if bodies:
        title, body = max(bodies, key=lambda item: len(item[1]))
    else:
        body = ''.join(parser.text)
    body = '\n'.join(line.strip() for line in body.splitlines() if line.strip())
    return str(title)[:180], str(title) + '\n' + body


def fetch_note(url):
    check_url(url)
    try:
        with direct_opener(PublicRedirect()).open(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=25) as response:
            data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise ValueError('笔记页面超过4MiB')
            kind = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or 'utf-8'
            text = data.decode(charset)
            final_url = response.geturl()
        title, note = extract_note(text) if kind in ('text/html', 'application/xhtml+xml') else ('URL笔记', text)
        if kind not in ('text/html', 'application/xhtml+xml', 'text/plain'):
            raise ValueError('URL必须是网页正文或纯文本')
        from ..parsing import parse_note
        if not parse_note(note, source_url=None, log_results=False).items:
            raise ValueError('未读取到有效报价正文；页面可能需要登录，请改用TXT上传')
        return final_url, title, note
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('笔记URL读取失败，请检查链接或改用TXT上传') from exc
