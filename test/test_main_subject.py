from modou.main_subject import classify
from modou.main_subject import MainSubjects
import io
import zipfile


def test_default_self_only_after_successful_lookup():
    path = io.BytesIO()
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('subject-relations.jsonlines', '')
    class API:
        def request(self, path):
            return []
    resolver = MainSubjects(path, API())
    assert resolver.resolve({'id': 123})['status'] == 'default_self'
    assert resolver.resolve({'id': 123})['main_id'] == '123'
    assert resolver.resolve({})['main_id'] is None
    class Failed:
        def request(self, path):
            raise OSError('offline')
    assert MainSubjects(path, Failed()).resolve({'id': 123})['main_id'] is None


def test_self_rendering_and_parent_link():
    from modou.review_html import main_subject_link
    assert main_subject_link('123', 123) == '<span style="color:#64748B">（123）</span>'
    assert '<a ' in main_subject_link('456', 123)
    for value in (None, ''):
        assert main_subject_link(value) == '<span style="background:#F53535;color:#000;font-weight:700">？</span>'


def test_self_from_reverse_relation():
    assert classify('1', [('2', '1')])['main_id'] == '1'


def test_parent_and_self_terminal():
    assert classify('2', [('2', '1')])['main_id'] == '1'
    assert classify('1', [('1', '1')])['status'] == 'self'


def test_conflict_and_missing():
    assert classify('1', [('1', '2'), ('2', '1')])['status'] == 'conflict'
    assert classify('1', [])['main_id'] is None
    assert classify('1', [('1', '2'), ('1', '3')])['status'] == 'conflict'
