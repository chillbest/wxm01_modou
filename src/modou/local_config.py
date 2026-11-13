"""Read local dotenv literals without printing secrets or changing process environment."""
import os
from pathlib import Path


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
