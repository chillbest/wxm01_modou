import logging
import uuid
from pathlib import Path

import pytest

from modou import logging_setup as logs
from modou.bangumi import resolve
from modou.parsing import parse_note


@pytest.fixture
def logdir():
    path = Path('.tmp') / ('logging-' + uuid.uuid4().hex)
    logs.setup(path)
    yield path
    for handler in list(logs.logger.handlers):
        if getattr(handler, '_modou_owned', False):
            logs.logger.removeHandler(handler)
            handler.close()


def read(path):
    return next(path.glob('modou_*.log')).read_text(encoding='utf-8')


def test_rotation_and_repeat_setup(logdir):
    logs.setup(logdir, max_bytes=600, backups=2)
    logs.setup(logdir, max_bytes=600, backups=2)
    assert sum(getattr(h, '_modou_owned', False) for h in logs.logger.handlers) == 2
    for i in range(20):
        logs.event('轮转验证', index=i)
    assert bool(list(logdir.glob('modou_*.log.1')))
    assert not list(logdir.glob('modou_*.log.3'))


def test_secrets_injection_and_context(logdir, monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'private-secret-123')
    with logs.context(run_id='run1', note_id='笔记.txt'):
        logs.event('测试', raw_name='private-secret-123\n伪造日志', url='postgresql://user:pass@host/db', token='token=hidden')
    logs.event('结束')
    content = read(logdir)
    assert 'private-secret-123' not in content and 'user:pass' not in content and 'hidden' not in content
    assert len(content.splitlines()) == 2
    assert "run_id='run1'" in content and "note_id='笔记.txt'" in content
    assert "run_id='-'" in content.splitlines()[-1]


class API:
    def __init__(self, rows=(), error=None):
        self.rows, self.error = list(rows), error
    def search(self, query):
        if self.error:
            raise self.error
        return self.rows


@pytest.mark.parametrize('aliases,local,api,ai,expected', [
    ([{'alias': '游戏', 'gpc_id': 2, 'name_zh': '标准名'}], [], API(), None, '已识别'),
    ([], [{'id': 4, 'name_cn': '中文名'}], API(), None, '已识别'),
    ([], [], API([{'id': 5, 'name_cn': '在线名'}]), None, '已识别'),
    ([], [], API(), None, '未识别'),
    ([], [], API(error=TimeoutError('secret')), None, '未识别'),
    ([], [{'id': 1}, {'id': 2}], API(), None, '歧义'),
    ([], [{'id': 1}, {'id': 2}], API(), lambda _: {'bangumi_id': 2}, '已识别'),
    ([], [], API(), lambda _: {'bangumi_id': 999}, '未识别'),
])
def test_resolution_trace(logdir, aliases, local, api, ai, expected):
    result = resolve('游戏', 'PRIVATE NOTE BODY', aliases, local, api, ai, note_id='note.txt', line_number=8)
    content = read(logdir)
    for stage in ('本地别名', 'Bangumi本地资料', 'BangumiAPI', 'DeepSeek'):
        assert stage in content
    assert '条目最终结果' in content and expected in content
    assert "line='8'" in content and 'note.txt' in content
    assert 'PRIVATE NOTE BODY' not in content and 'secret' not in content
    assert result['status'] == 'pending'
    if isinstance(api.error, TimeoutError):
        assert '请求超时' in content


def test_parser_logs_each_item_and_summary(logdir):
    result = parse_note('标题\n游戏甲｜HK100\n游戏乙｜HK200', note_id='note.txt')
    content = read(logdir)
    assert len(result.items) == 2
    assert content.count('条目最终结果') == 2
    assert '游戏甲' in content and '游戏乙' in content and '笔记汇总' in content


def test_request_failure_has_id_and_safe_reason(logdir):
    @logs.logged_request('测试API')
    def request():
        raise TimeoutError('DO NOT LOG ME')
    with pytest.raises(TimeoutError):
        request()
    content = read(logdir)
    assert '外部调用失败' in content and '请求超时' in content and 'elapsed_seconds' in content
    assert 'DO NOT LOG ME' not in content
    assert "request_id='-'" not in content


def test_transaction_commit_and_rollback(logdir):
    from contextlib import contextmanager
    class Engine:
        @contextmanager
        def begin(self):
            yield object()
    with logs.logged_transaction(Engine()):
        logs.event('写入完成')
    with pytest.raises(ValueError):
        with logs.logged_transaction(Engine()):
            raise ValueError('PRIVATE PASSWORD')
    content = read(logdir)
    assert content.count('导入事务已提交') == 1
    assert content.count('导入事务失败并回滚') == 1
    assert 'PRIVATE PASSWORD' not in content
    assert "batch_id='-'" not in content


def test_entry_failure_and_runtime(logdir, monkeypatch):
    monkeypatch.setattr(logs, 'setup', lambda: None)
    @logs.logged_main
    def main():
        raise ValueError('PRIVATE CONFIG')
    with pytest.raises(ValueError):
        main()
    content = read(logdir)
    assert '运行开始' in content and '运行失败' in content and 'elapsed_seconds' in content
    assert 'PRIVATE CONFIG' not in content
    assert "run_id='-'" not in content


def test_task_date_stays_fixed_across_midnight(logdir, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    logdir = logdir / 'midnight'
    logs.setup(logdir, started_at=datetime(2026,11,14,23,59,tzinfo=ZoneInfo('Asia/Shanghai')))
    logs.event('before midnight')
    monkeypatch.setattr(logs.time, 'time', lambda: 1794672060)
    logs.event('after midnight')
    content=(logdir/'modou_2026-11-14.log').read_text(encoding='utf-8')
    assert 'before midnight' in content and 'after midnight' in content
    assert not (logdir/'modou_2026-11-15.log').exists()
