"""Exercise the PowerShell script with mocked networking and process commands."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_stop_web_process_guards():
    shell = shutil.which('pwsh')
    if not shell:
        pytest.skip('PowerShell 7 is not installed')
    subprocess.run([shell, '-NoProfile', '-File', str(Path(__file__).with_suffix('.ps1'))],
                   check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
