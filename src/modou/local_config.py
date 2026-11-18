"""Read local dotenv literals without printing secrets or changing process environment."""
import os
import tomllib
from pathlib import Path


def read_max_output_tokens(path=None):
    path = Path(path) if path is not None else Path(__file__).resolve().parents[2] / "config.toml"
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
        value = data["deepseek"]["max_output_tokens"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("config.toml须包含[deepseek].max_output_tokens正整数配置") from exc
    if type(value) is not int or value <= 0:
        raise ValueError("deepseek.max_output_tokens必须为正整数")
    return value


def read_config(path=Path(".env")):
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.strip().partition("=")
            if separator and key and not key.startswith("#"):
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                values[key.strip()] = value
    # Explicit process configuration wins; generic DATABASE_URL is deliberately unused.
    for key in ["DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "MODOU_TEST_DATABASE_URL", "POSTGRES_PASSWORD"]:
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def read_bangumi_proxy_url(path=None):
    """Only the project TOML controls the Bangumi HTTP proxy."""
    from urllib.parse import urlsplit
    path = Path(path) if path is not None else Path(__file__).resolve().parents[2] / 'config.toml'
    try:
        with path.open('rb') as stream:
            value = tomllib.load(stream)['bangumi']['proxy_url']
        if not isinstance(value, str) or value != value.strip() or any(c.isspace() for c in value):
            raise ValueError()
        parts = urlsplit(value)
        if (parts.scheme != 'http' or not parts.hostname or not parts.port
                or parts.username is not None or parts.password is not None
                or parts.path not in ('', '/') or parts.query or parts.fragment):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError('config.toml须包含[bangumi].proxy_url，格式为http://主机:端口（不含账号密码）') from exc
    return value
