"""Proxy boundaries tested with local sockets; no external requests or API keys."""
import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4
from urllib.error import URLError
from urllib.request import ProxyHandler, Request

import pytest

from modou import http_transport as transport
from modou.bangumi import AnonymousAPI
from modou.local_config import read_bangumi_proxy_url


@pytest.fixture
def config_path():
    path = Path('.tmp') / ('http-config-' + uuid4().hex) / 'config.toml'
    path.parent.mkdir(parents=True)
    return path.resolve()


def test_proxy_config_is_explicit_and_independent_of_cwd(config_path, monkeypatch):
    config_path.write_text('[bangumi]\nproxy_url="http://127.0.0.1:7897"\n', encoding='utf-8')
    assert read_bangumi_proxy_url(config_path) == 'http://127.0.0.1:7897'
    monkeypatch.chdir(config_path.parent)
    assert read_bangumi_proxy_url() == 'http://127.0.0.1:7897'


@pytest.mark.parametrize('value', ['', 'socks5://127.0.0.1:7897', 'https://127.0.0.1:7897',
    'http://127.0.0.1', 'http://127.0.0.1:0', 'http://127.0.0.1:65536',
    'http://user:pass@127.0.0.1:7897', 'http://127.0.0.1:7897/path',
    'http://127.0.0.1:7897?x=1', ' http://127.0.0.1:7897', None, True])
def test_invalid_proxy_never_silently_uses_environment(config_path, value):
    import json
    literal = json.dumps(value) if value is not None else '[]'
    config_path.write_text('[bangumi]\nproxy_url=' + literal + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='proxy_url'):
        read_bangumi_proxy_url(config_path)


def test_missing_proxy_is_an_error(config_path):
    with pytest.raises(ValueError, match='proxy_url'):
        read_bangumi_proxy_url(config_path)
    config_path.write_text('[deepseek]\nmax_output_tokens=3000\n', encoding='utf-8')
    with pytest.raises(ValueError, match='proxy_url'):
        read_bangumi_proxy_url(config_path)


@pytest.fixture
def local_http():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_CONNECT(self):
            calls.append(('CONNECT', self.path))
            self.send_error(502, 'Test proxy refuses tunnel')
        def do_GET(self):
            calls.append(('GET', self.path))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'direct')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port), calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_bangumi_uses_configured_proxy_despite_no_proxy_and_no_fallback(local_http, monkeypatch):
    proxy, calls = local_http
    monkeypatch.setattr(transport, 'read_bangumi_proxy_url', lambda: proxy)
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:1')
    monkeypatch.setenv('NO_PROXY', '*')
    monkeypatch.setattr('urllib.request.proxy_bypass', lambda host: True)
    with pytest.raises(URLError):
        AnonymousAPI().request('/v0/subjects/4')
    assert calls == [('CONNECT', 'api.bgm.tv:443')]


def test_other_http_is_direct_despite_environment_and_system_proxy(local_http, monkeypatch):
    target, calls = local_http
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1')
    monkeypatch.setenv('NO_PROXY', '')
    monkeypatch.setattr('urllib.request.getproxies', lambda: {'http':'http://127.0.0.1:1'})
    with transport.direct_urlopen(Request(target + '/test'), timeout=2) as response:
        assert response.read() == b'direct'
    assert calls == [('GET','/test')]


@pytest.mark.parametrize('url', ['https://api.deepseek.com/test','https://api.bgm.tv.evil.test/test',
    'http://api.bgm.tv/test','https://user@api.bgm.tv/test','https://api.bgm.tv:444/test'])
def test_proxy_rejects_other_hosts_and_cross_host_redirects(url):
    with pytest.raises(ValueError, match='仅允许'):
        transport.bangumi_urlopen(Request(url), timeout=2)
    with pytest.raises(ValueError, match='仅允许'):
        transport._BangumiRedirect().redirect_request(Request('https://api.bgm.tv/test'), None, 302, '', {}, url)


def test_same_host_redirect_retains_proxy_routing():
    handler = transport._BangumiRedirect()
    redirected = handler.redirect_request(Request('https://api.bgm.tv/test'), None, 302, '', {}, 'https://api.bgm.tv/next')
    transport._BangumiProxy({'https':'http://127.0.0.1:7897'}).https_open(redirected)
    assert redirected.host == '127.0.0.1:7897'
    assert redirected._tunnel_host == 'api.bgm.tv'


def test_deepseek_defaults_and_gamefaqs_use_direct_transport(monkeypatch):
    from modou import bangumi_cli, deepseek
    from modou.web import links
    assert bangumi_cli.urlopen is transport.direct_urlopen
    assert deepseek.DeepSeek('fake-key').transport is transport.direct_urlopen
    seen=[]
    def opener(*handlers):
        assert handlers == (links.NoRedirect,)
        class Direct:
            def open(self, req, timeout):
                seen.append((req.full_url, timeout))
                return io.BytesIO(b'<title>Game</title>')
        return Direct()
    monkeypatch.setattr(links, 'direct_opener', opener)
    url='https://gamefaqs.gamespot.com/ps5/450686-elden-ring-shadow-of-the-erdtree-edition'
    assert links.gamefaqs(url)['outlink'] == url
    assert seen == [(url,20)]
