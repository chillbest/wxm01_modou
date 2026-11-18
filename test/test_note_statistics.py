import io
import logging
import uuid
from pathlib import Path

import pytest

from modou import logging_setup as logs
from modou.parsing import parse_note


@pytest.fixture
def capture():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logs.SafeFormatter('%(message)s'))
    logs.logger.addHandler(handler)
    old = logs.logger.level
    logs.logger.setLevel(logging.INFO)
    yield stream
    logs.logger.removeHandler(handler)
    logs.logger.setLevel(old)


def block(stream):
    text = stream.getvalue()
    return text[text.index('笔记统计｜'):].strip().splitlines()


def test_three_lines_spacing_and_exclusive_time(capture, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(logs.time, 'monotonic', lambda: clock[0])
    logs.event('前一条')
    with logs.context(run_id='run1'), logs.note_statistics('目录/笔记.txt'):
        logs.note_total(3)
        clock[0] = 1
        with logs.note_phase('本地查询'):
            clock[0] = 3
        with logs.note_phase('联网识别'):
            clock[0] = 7
        with logs.note_phase('输出'):
            clock[0] = 8
        for result in ('已识别', '歧义', '未识别'):
            logs.event('条目最终结果', result=result)
    lines = block(capture)
    assert len(lines) == 3
    assert '《笔记.txt》' in lines[0] and '开始20' in lines[0] and '总耗时8.00秒' in lines[0]
    assert '条目3｜已识别1｜歧义1｜未识别1｜未处理0' in lines[1]
    assert lines[2] == '耗时：读取/规则1.00秒｜本地查询2.00秒｜联网识别4.00秒｜输出1.00秒'
    assert '\n\n\n笔记统计｜' in capture.getvalue()
    assert capture.getvalue().endswith('输出1.00秒\n\n\n')


def test_failure_reports_unprocessed_and_phase(capture):
    with pytest.raises(TimeoutError):
        with logs.note_statistics('失败.txt'):
            logs.note_total(5)
            logs.event('条目最终结果', result='已识别')
            with logs.note_phase('输出'):
                raise TimeoutError('PRIVATE SECRET')
    lines = block(capture)
    assert '失败：输出/请求超时' in lines[0]
    assert '条目5｜已识别1｜歧义0｜未识别0｜未处理4' in lines[1]
    assert 'PRIVATE SECRET' not in capture.getvalue()


def test_unknown_count_and_injected_name(capture):
    with pytest.raises(OSError):
        with logs.note_statistics('坏\n名字.txt'):
            raise OSError('secret')
    assert len(block(capture)) == 3
    assert '条目未知' in block(capture)[1]


def test_batch_two_independent_notes(capture, monkeypatch):
    from modou import memory_cli
    directory = Path('.tmp') / ('statistics-' + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    (directory / 'a.txt').write_text('标题\n游戏｜HK100', encoding='utf-8')
    (directory / 'b.txt').write_text('标题\n游戏｜HK100\n另一游戏｜HK200', encoding='utf-8')
    (directory / 'manifest.json').write_text('[{"path":"a.txt","date":"2026-11-15"},{"path":"b.txt","date":"2026-11-15"}]', encoding='utf-8')
    monkeypatch.setattr(memory_cli, 'read_test_catalog', lambda values: [])
    result = memory_cli.run(directory / 'manifest.json', directory / 'out', values={})
    assert len(result['notes']) == 2
    text = capture.getvalue()
    assert text.count('笔记统计｜') == 2
    assert '《a.txt》' in text and '《b.txt》' in text
    assert '条目1｜已识别0｜歧义0｜未识别1｜未处理0' in text
    assert '条目2｜已识别0｜歧义0｜未识别2｜未处理0' in text
    assert text.count('共享准备耗时另计') == 2


def test_excluded_digital_section_does_not_inflate_count(capture):
    with logs.note_statistics('x.txt'):
        parse_note('标题\n游戏｜HK100\n——数字折扣——\n数字游戏｜HK20')
    assert '条目1｜' in block(capture)[1]


def test_note_review_has_no_duplicate_results(capture, monkeypatch):
    from modou.note_review import build_review
    class Main:
        def __init__(self, *args): pass
        def resolve(self, chosen): return {'status': 'self', 'main_id': '4'}
    monkeypatch.setattr('modou.main_subject.MainSubjects', Main)
    class Local:
        path = Path('dump.zip')
        def lookup_many(self, queries):
            return {'游戏': [{'id': 4, 'name_cn': '游戏'}]}
    class API:
        def search(self, query):
            raise AssertionError('should not request')
    with logs.note_statistics('x.txt'):
        rows = build_review('标题\n游戏｜HK100', 'x.txt', None, [], Local(), API())
    assert len(rows) == 1
    assert '条目1｜已识别1｜歧义0｜未识别0｜未处理0' in block(capture)[1]


@pytest.mark.parametrize('module, argv', [
    ('parse_cli', ['parse', 'INPUT', '--output', 'OUTPUT']),
    ('bangumi_cli', ['bgm', 'review', 'INPUT']),
    ('note_review', ['note', 'review', 'INPUT']),
])
def test_cli_file_summary_and_failure(capture, monkeypatch, module, argv):
    import importlib
    import sys
    cli = importlib.import_module('modou.' + module)
    directory = Path('.tmp') / ('statistics-cli-' + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    source = directory / 'note.txt'
    source.write_text('标题\n游戏｜HK100', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', [str(source) if a == 'INPUT' else str(directory / 'out.json') if a == 'OUTPUT' else a for a in argv])
    if module == 'parse_cli':
        cli.main.__wrapped__()
        assert '成功' in block(capture)[0]
    else:
        monkeypatch.setattr(cli, 'read_config', lambda path: {})
        if module == 'bangumi_cli':
            source.write_text('[{"raw_name":"游戏","note":"标题"}]', encoding='utf-8')
        def fail(values):
            raise ValueError('PRIVATE DATABASE URL')
        monkeypatch.setattr(cli, 'engine_for', fail)
        with pytest.raises(ValueError):
            cli.main.__wrapped__()
        assert '失败' in block(capture)[0]
        assert 'PRIVATE DATABASE URL' not in capture.getvalue()
    assert len(block(capture)) == 3


def test_summary_file_has_exact_blank_lines(capture):
    directory = Path('.tmp') / ('statistics-file-' + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    handler = logging.FileHandler(directory / 'sample.log', encoding='utf-8')
    handler.setFormatter(logs.SafeFormatter('%(message)s'))
    logs.logger.addHandler(handler)
    try:
        logs.event('before')
        with logs.note_statistics('测试.txt'):
            logs.note_total(0)
        logs.event('after')
    finally:
        logs.logger.removeHandler(handler)
        handler.close()
    text = (directory / 'sample.log').read_text(encoding='utf-8')
    assert '\n\n\n笔记统计｜' in text
    assert '秒\n\n\nafter' in text


def test_recovered_request_error_does_not_mask_output_failure(capture):
    with pytest.raises(OSError):
        with logs.note_statistics('x.txt'):
            try:
                with logs.note_phase('联网识别'):
                    raise TimeoutError()
            except TimeoutError:
                pass
            with logs.note_phase('输出'):
                raise OSError()
    assert '失败：输出/' in block(capture)[0]
