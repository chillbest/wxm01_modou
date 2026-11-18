import io
import json
import pytest
from modou.local_config import read_max_output_tokens
from modou import bangumi_cli
from pathlib import Path
from uuid import uuid4


@pytest.fixture
def config_dir():
    directory = Path(__file__).resolve().parents[1] / '.tmp' / ('deepseek-config-' + uuid4().hex)
    directory.mkdir(parents=True)
    return directory



def test_load_output_limit(config_dir, monkeypatch):
    config = config_dir / 'config.toml'
    config.write_text('[deepseek]\nmax_output_tokens = 8192\n', encoding='utf-8')
    assert read_max_output_tokens(config) == 8192
    monkeypatch.chdir(config_dir)
    import tomllib
    root_config = Path(__file__).resolve().parents[1] / 'config.toml'
    assert read_max_output_tokens() == tomllib.loads(root_config.read_text(encoding='utf-8'))['deepseek']['max_output_tokens']  # Independent of cwd.


@pytest.mark.parametrize('body', ['', '[deepseek]', '[deepseek]\nmax_output_tokens = 0', '[deepseek]\nmax_output_tokens = -1', '[deepseek]\nmax_output_tokens = true', '[deepseek]\nmax_output_tokens = "1024"', '[deepseek]\nmax_output_tokens = 1.5', '[deepseek'])
def test_reject_invalid_configuration(config_dir, body):
    config = config_dir / 'config.toml'
    config.write_text(body, encoding='utf-8')
    with pytest.raises(ValueError, match='max_output_tokens'):
        read_max_output_tokens(config)


def test_missing_configuration(config_dir):
    with pytest.raises(ValueError, match='max_output_tokens'):
        read_max_output_tokens(config_dir / 'absent.toml')


def test_both_ai_tasks_use_configured_api_limit(monkeypatch):
    monkeypatch.setattr(bangumi_cli, 'read_max_output_tokens', lambda: 8192)
    requests = []
    def respond(request, timeout):
        payload = json.loads(request.data)
        requests.append(payload)
        return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop', 'message':{'content':'{"candidate": null}'}}]}).encode())
    monkeypatch.setattr(bangumi_cli, 'urlopen', respond)
    client = bangumi_cli.ai_client({'DEEPSEEK_API_KEY':'test'})
    client({'raw_name':'test'})
    client({'task':'gamefaqs','raw_name':'test'})
    assert len(requests) == 2
    assert all(p['max_tokens'] == 8192 and 'max_output_tokens' not in p for p in requests)
