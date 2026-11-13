"""从本地.env加载凭证，运行NAS专用测试库验收。"""
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import URL


def main():
    root = Path(__file__).resolve().parents[1]
    values = {}
    for line in (root / ".env").read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            values[key.strip()] = value
    if not values.get("POSTGRES_PASSWORD"):
        raise SystemExit(".env缺少POSTGRES_PASSWORD")
    url = URL.create("postgresql+psycopg", username="modou", password=values["POSTGRES_PASSWORD"], host="192.168.1.23", port=15432, database="modou_test")
    env = os.environ.copy()
    env["MODOU_TEST_DATABASE_URL"] = url.render_as_string(hide_password=False)
    # 禁止失败时打印含连接环境的测试上下文。
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=no"], cwd=root, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
