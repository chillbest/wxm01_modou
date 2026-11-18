"""Explicit HTTP routing: only Bangumi API uses the configured proxy."""
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .local_config import read_bangumi_proxy_url


def direct_opener(*handlers):
    # Empty mapping disables both environment and Windows registry proxies.
    return build_opener(ProxyHandler({}), *handlers)


def direct_urlopen(request, timeout):
    return direct_opener().open(request, timeout=timeout)


def _check_bangumi(url):
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.hostname != 'api.bgm.tv'
            or parts.port not in (None, 443) or parts.username is not None or parts.password is not None):
        raise ValueError('Bangumi代理仅允许https://api.bgm.tv请求')


class _BangumiProxy(ProxyHandler):
    def proxy_open(self, req, proxy, type):
        _check_bangumi(req.full_url)
        # Unlike the standard ProxyHandler, NO_PROXY/system bypass rules must
        # not silently turn a configured Bangumi request into a direct request.
        req.set_proxy(urlsplit(proxy).netloc, 'http')


class _BangumiRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_bangumi(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def bangumi_urlopen(request, timeout):
    url = request.full_url if isinstance(request, Request) else request
    _check_bangumi(url)
    proxy = read_bangumi_proxy_url()
    # An isolated opener: never install global handlers or retry without proxy.
    return build_opener(_BangumiProxy({'https': proxy}), _BangumiRedirect()).open(request, timeout=timeout)
