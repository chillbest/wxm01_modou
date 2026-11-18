import shutil
import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from modou.review_html import original_with_section, render_html
from modou.parsing import parse_note
from modou.web.app import create_app
from modou.web.store import display_filename
from test_web_app import row, HEADERS, tmp_path


def test_home_flow_javascript():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    subprocess.run([node, 'test/test_home_flow.cjs'], check=True, capture_output=True)


def test_section_prefix_from_actual_parser():
    parsed = parse_note('标题\n——💭实时新增————\n🔹只狼｜🇭🇰203｜凑-50\n——💭福8-80区——\n🔸红色沙漠｜🇭🇰257', log_results=False)
    for item, expected in zip(parsed.items, ['🔹只狼｜🇭🇰203｜凑-50（实时新增）', '🔸红色沙漠｜🇭🇰257（福8-80区）']):
        r = row();r['extracted'] = item.model_dump(mode="json")
        assert original_with_section(r) == expected
        assert expected in render_html([r], 'test.txt', None, online=True)
    assert original_with_section({'raw_name':'旧记录'}) == '旧记录'
    r=row();r['extracted']={'section':'——<script>——','raw_line':'<img>'}
    assert '<img>' not in render_html([r], 'test', None, online=True)


def test_url_batch_title_metadata_and_api(tmp_path, monkeypatch):
    monkeypatch.setattr('modou.web.url_note.fetch_note',lambda url:(url,'正文标题','正文标题\n内容'))
    app=create_app(tmp_path, duplicate_checker=lambda _:None)
    app.state.parse_job=lambda *args:None
    with TestClient(app) as client:
        for _ in range(3):
            response=client.post('/api/url',headers=HEADERS,json={'url':'https://example.com/note'})
            assert response.status_code==200
        batches=client.get('/api/batches').json()
        assert batches[-1]['display_filename']=='url：正文标题（3）'
        assert batches[-1]['created_at']
        assert display_filename({'filename':'旧标题.txt','source_path':'https://example.com','upload_index':2})=='url：旧标题（2）'
        assert display_filename({'filename':'11.3A｜Ps好价光盘.txt','upload_index':3})=='11.3A｜Ps好价光盘.txt（3）'

