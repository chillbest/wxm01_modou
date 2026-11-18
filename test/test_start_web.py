"""Exercise the PowerShell script with mocked networking and process commands."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('shell_name', ['pwsh', 'powershell'])
def test_start_web_restart_guards(shell_name):
    shell = shutil.which(shell_name)
    if not shell:
        pytest.skip('PowerShell 7 is not installed')
    subprocess.run([shell, '-NoProfile', '-File', str(Path(__file__).with_suffix('.ps1'))],
                   check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")


@pytest.mark.parametrize('shell_name', ['pwsh', 'powershell'])
def test_web_scripts_parse(shell_name):
    shell = shutil.which(shell_name)
    if not shell:
        pytest.skip(f'{shell_name} is not installed')
    root = Path(__file__).resolve().parents[1]
    for name in ('start_web.ps1', 'stop_web.ps1'):
        path = str(root / 'scripts' / name).replace("'", "''")
        command = ("$errors = $null; $tokens = $null; "
                   f"[void][System.Management.Automation.Language.Parser]::ParseFile('{path}', "
                   "[ref]$tokens, [ref]$errors); if ($errors.Count) { throw ($errors | Out-String) }")
        subprocess.run([shell, '-NoProfile', '-Command', command], check=True,
                       capture_output=True, text=True, errors='replace')

