"""LAN HTTP boundary. Credentials and database access remain server-side."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.exc import SQLAlchemyError
from ..logging_setup import event
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from ..review_html import render_html
from ..web_review import eligibility_errors
from .store import Store, Conflict, display_filename, persisted
from .service import parse_job, public_batch, edit_row, select_row, commit_batch, hydrate_candidate, restore_row, reparse_one, refresh_duplicates
from .duplicates import SimilarProducts
from .links import subject, gamefaqs, suggest_main
from ..local_config import read_config
from ..bangumi_cli import ai_client

BASE = Path(__file__).resolve().parent


def program_modified_at(source_root=None):
    """Latest deployed source/resource mtime; runtime data is deliberately excluded."""
    source_root = Path(source_root) if source_root is not None else BASE.parent
    paths = [p for p in source_root.rglob('*')
             if p.is_file() and '__pycache__' not in p.parts
             and (p.suffix == '.py' or p.is_relative_to(source_root / 'web' / 'static'))]
    return datetime.fromtimestamp(max(p.stat().st_mtime for p in paths), ZoneInfo('Asia/Shanghai')).strftime('%Y/%m/%d %H:%M')


def create_app(root=None, dump_dir=None, *, duplicate_checker=None):
    root = Path(root or os.environ.get('MODOU_WEB_DATA', 'data/web'))
    store = Store(root / 'batches')
    uploads = root / 'uploads'
    uploads.mkdir(parents=True, exist_ok=True)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='modou-parser')
    reparse_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='modou-reparse')
    candidate_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='modou-candidate')
    # A terminated server cannot leave a forever-running job in the UI.
    for path in store.root.glob('*.json'):
        value = json.loads(path.read_text(encoding='utf-8'))
        if value['state'] in ('queued', 'parsing', 'reviewable'):
            value.update(state='failed', error='服务已重启，请重新上传解析', revision=value['revision'] + 1)
            store.write(value)

    @asynccontextmanager
    async def lifespan(app):
        yield
        pool.shutdown(wait=True)
        reparse_pool.shutdown(wait=True)
        candidate_pool.shutdown(wait=True)

    app = FastAPI(title='魔豆在线审核', lifespan=lifespan)
    app.state.store = store
    app.state.parse_job = parse_job
    app.state.commit_batch = commit_batch
    app.state.refresh_duplicates = duplicate_checker or refresh_duplicates
    app.mount('/assets', StaticFiles(directory=BASE / 'static'), name='assets')

    @app.middleware('http')
    async def same_origin(request, call_next):
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            origin = request.headers.get('origin')
            if origin and urlsplit(origin).netloc != request.headers.get('host'):
                return JSONResponse({'detail': '拒绝跨站写入请求'}, status_code=403)
            if request.headers.get('x-modou-review') != '1':
                return JSONResponse({'detail': '缺少审核请求标识'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'none'"
        return response

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=422)

    @app.exception_handler(SimilarProducts)
    async def similar(request, exc):
        return JSONResponse({'detail': str(exc), 'similar_products': exc.conflicts}, status_code=409)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        event('网页数据库操作失败', reason=type(exc).__name__)
        return JSONResponse({'detail': '数据库操作失败，本次事务未提交；请检查连接或日志后重试'}, status_code=503)

    def load(key):
        try:
            with store.lock:
                batch = store.read(key)
                before = json.dumps(persisted(batch), sort_keys=True, default=str)
                app.state.refresh_duplicates(batch)
                if json.dumps(persisted(batch), sort_keys=True, default=str) != before:
                    batch['revision'] += 1
                    store.write(batch)
                return batch
        except FileNotFoundError:
            raise HTTPException(404, '批次不存在')

    def mutate(key, payload, fn):
        load(key)
        def change(batch):
            fn(batch)
            app.state.refresh_duplicates(batch)
        return public_batch(store.update(key, payload['revision'], change))

    @app.get('/', response_class=HTMLResponse)
    def home():
        return (BASE / 'static' / 'index.html').read_text(encoding='utf-8').replace('{{program_modified_at}}', program_modified_at())

    @app.get('/api/batches')
    def batches():
        return [{**{k: b.get(k) for k in ('id', 'filename', 'state', 'created_at', 'error', 'parse_started_at', 'parse_finished_at', 'parse_elapsed_seconds', 'upload_index')},
                 'display_filename': display_filename(b),
                 'imported_count': sum(bool(r.get('imported') or r.get('already_imported')) for r in b['rows']),
                 'total_rows': b.get('total_rows', len(b['rows']) if b['state'] == 'ready' else None)}
                for b in store.list()]

    @app.post('/api/upload')
    def upload(file: UploadFile = File(...)):
        filename = (file.filename or '').replace('\\', '/').split('/')[-1]
        if not filename.lower().endswith('.txt') or not filename.strip('.txt'):
            raise ValueError('仅支持TXT文件')
        content = file.file.read(4 * 1024 * 1024 + 1)
        if len(content) > 4 * 1024 * 1024:
            raise ValueError('TXT不能超过4MiB')
        digest = hashlib.sha256(content).hexdigest()
        # Preserve filename for date inference, but never use client path components.
        safe = ''.join(c if c.isalnum() or c in '.-_｜ ' else '_' for c in filename)[:180]
        folder = uploads / digest
        folder.mkdir(exist_ok=True)
        path = folder / safe
        path.write_bytes(content)
        batch = store.create(filename, 'uploads/' + digest + '/' + safe)
        pool.submit(app.state.parse_job, store, batch['id'], path, dump_dir or os.environ.get('MODOU_BANGUMI_DUMP', 'data/bangumi_locale'))
        return {'id': batch['id'], 'url': '/review/' + batch['id']}

    @app.get('/api/batches/{key}')
    def get_batch(key: str):
        return public_batch(load(key))

    @app.get('/api/batches/{key}/updates')
    def updates(key: str, after: int = 0):
        b = load(key)
        if not 0 <= after <= len(b['rows']):
            raise ValueError('追加位置无效')
        html = render_html(b['rows'][after:], display_filename(b), None, start_index=after + 1, online=True)
        return {'batch': public_batch(b), 'html': html}

    @app.get('/review/{key}', response_class=HTMLResponse)
    def review(key: str):
        batch = load(key)
        if not batch['rows']:
            return '<!doctype html><meta charset="utf-8"><title>' + escape(display_filename(batch)) + '</title><body><main id="pending"><h2>解析状态</h2><p id="parse-status"></p><a href="/" target="_self">返回首页</a></main><script src="/assets/pending.js"></script></body>'
        day = next((r['quote'].get('published_at') for r in batch['rows']), None)
        html = render_html(batch['rows'], display_filename(batch), date.fromisoformat(day) if day else None, online=True)
        # Include the new main-subject interaction without changing original evidence.
        evidence = ''.join('<details><summary>条目' + str(i + 1) + '：GameFAQs主版本识别证据</summary><pre>' + escape(json.dumps(r.get('main_resolution'), ensure_ascii=False, indent=2)) + '</pre></details>' for i, r in enumerate(batch['rows']) if r.get('ai_mode') != 'batch' and (r.get('main_resolution') or {}).get('source') == 'deepseek_gamefaqs')
        data = json.dumps(public_batch(batch), ensure_ascii=False, default=str).replace('<', '\\u003c')
        extra = '<link rel="stylesheet" href="/assets/review.css"><script id="web-batch" type="application/json">' + data + '</script>' + evidence + '<script src="/assets/review.js"></script>'
        return html.replace('</body>', extra + '</body>')

    @app.post('/api/batches/{key}/rows/{index}')
    def save_row(key: str, index: int, payload: dict):
        batch = load(key)
        if not 0 <= index < len(batch['rows']):
            raise HTTPException(404, '条目不存在')
        return mutate(key, payload, lambda b: edit_row(b, index, payload))

    @app.post('/api/batches/{key}/rows/{index}/blacklist')
    def blacklist(key: str, index: int, payload: dict):
        from .service import blacklist_row
        return mutate(key, payload, lambda b: blacklist_row(b, index, payload))

    @app.post('/api/batches/{key}/rows/{index}/candidate')
    def pick_candidate(key: str, index: int, payload: dict):
        from .candidate_pick import choose, complete
        resolved_candidate = None
        manual_gamefaqs = False
        manual_english = None
        if payload.get('url'):
            from ..bangumi import english_name
            url = str(payload['url']).strip()
            from .links import valid_vgcollect_link
            from ..bangumi import valid_product_link
            if not valid_product_link(url):
                raise ValueError('外链必须是有效的HTTP/HTTPS URL')
            import re
            manual_gamefaqs = not re.fullmatch(r'https://(?:bgm\.tv|bangumi\.tv|chii\.in)/subject/[0-9]+/?', url)
            if manual_gamefaqs:
                if valid_vgcollect_link(url):
                    from .links import vgcollect
                    manual_english = vgcollect(url)
            else:
                try:
                    resolved_candidate = subject(url)
                except (OSError, TimeoutError) as exc:
                    raise ValueError('产品资料请求失败，链接未保存；请稍后重试') from exc
                resolved_candidate['name_en'] = english_name(resolved_candidate)
        with store.lock:
            current = store.read(key)
            if not 0 <= index < len(current['rows']):
                raise HTTPException(404, '条目不存在')
            row = current['rows'][index]
            lookup = row.get('candidate_lookup') or {}
            if type(payload.get('row_revision')) is not int:
                raise Conflict('缺少有效条目版本，请刷新后重试')
            enriched = (payload.get('lookup_status') == 'pending' and lookup.get('status') in ('done', 'failed')
                        and lookup.get('token') == payload.get('lookup_token')
                        and row.get('revision') == payload.get('row_revision', -2) + 1)
            if row.get('revision') != payload.get('row_revision') and not enriched:
                raise Conflict('条目已被修改，请刷新后重试')
            selected = []
            def change(batch):
                if manual_gamefaqs:
                    from .candidate_pick import save_manual_gamefaqs
                    save_manual_gamefaqs(batch, index, url, payload.get('display_name'), manual_english)
                else:
                    selected.extend(choose(batch, index, payload, resolved_candidate))
            saved = store.update(key, current['revision'], change)
        if manual_gamefaqs:
            return public_batch(saved)
        candidate, token, revision = selected
        candidate_pool.submit(complete, store, key, index, token, revision, candidate,
                              dump_dir or os.environ.get('MODOU_BANGUMI_DUMP', 'data/bangumi_locale'))
        return public_batch(saved)

    @app.get('/api/batches/{key}/rows/{index}/gpc')
    def gpc_preview(key: str, index: int):
        from .service import read_gpc, check_gpc_reload
        batch = load(key)
        check_gpc_reload(batch, index)
        return {'revision': batch['revision'], 'row_revision': batch['rows'][index]['revision'],
                'product': read_gpc(batch['rows'][index]['final']['gpc_id'])}

    @app.post('/api/batches/{key}/rows/{index}/reload-gpc')
    def gpc_reload(key: str, index: int, payload: dict):
        from .service import reload_gpc
        return mutate(key, payload, lambda b: reload_gpc(b, index, payload))

    @app.post('/api/batches/{key}/rows/{index}/restore')
    def restore(key: str, index: int, payload: dict):
        if not 0 <= index < len(load(key)['rows']):
            raise HTTPException(404, '条目不存在')
        return mutate(key, payload, lambda b: restore_row(b, index))

    @app.post('/api/batches/{key}/rows/{index}/reparse')
    def reparse(key: str, index: int, payload: dict):
        batch = load(key)
        if not 0 <= index < len(batch['rows']):
            raise HTTPException(404, '条目不存在')
        if batch['rows'][index].get('selected') or batch['rows'][index]['imported']:
            raise ValueError('请先取消勾选；已入库条目不能重新解析')
        if batch['revision'] != payload['revision']:
            raise Conflict('页面版本已过期，请刷新后重试')
        path = (root / batch.get('input_path', batch['source_path'])).resolve()
        if not path.is_relative_to(uploads.resolve()):
            raise ValueError('原始文件路径无效')
        replacement = reparse_pool.submit(reparse_one, batch, index, path, dump_dir or os.environ.get('MODOU_BANGUMI_DUMP', 'data/bangumi_locale')).result()
        def change(b):
            if persisted(b)['rows'][index] != persisted(batch)['rows'][index]:
                raise Conflict('条目已改变，请重试重新解析')
            b['rows'][index] = replacement
        return mutate(key, payload, change)

    @app.get('/api/preview/{sid}')
    def preview(sid: int):
        detail = subject('https://bgm.tv/subject/' + str(sid))
        from ..review_table import release_year, platform_text
        return {'name': detail.get('name_cn') or detail.get('name') or '中文名未提供',
                'year': release_year(detail),
                'platform': platform_text(detail),
                'image': (detail.get('images') or {}).get('common')}

    @app.post('/api/batches/{key}/select')
    def selection(key: str, payload: dict):
        def change(b):
            if not isinstance(payload.get('selected'), bool):
                raise ValueError('审核状态无效')
            if not isinstance(payload.get('index'), int) or not 0 <= payload['index'] < len(b['rows']):
                raise ValueError('条目编号无效')
            select_row(b, payload['index'], payload['selected'])
        return mutate(key, payload, change)

    @app.post('/api/batches/{key}/clear')
    def clear(key: str, payload: dict):
        def change(b):
            for row in b['rows']:
                if not row.get('already_imported') and not row.get('imported'):
                    row['selected'] = False
        return mutate(key, payload, change)

    @app.post('/api/batches/{key}/date')
    def set_date(key: str, payload: dict):
        from datetime import date
        day = date.fromisoformat(payload.get('date', '')).isoformat()
        def change(b):
            if any(r.get('selected') and not r['imported'] for r in b['rows']):
                raise ValueError('请先取消勾选，再修改出价日')
            b['review_date'] = day
            for row in b['rows']:
                if not row['imported'] and not row.get('already_imported'):
                    row['quote'].update(published_at=day, lowprice_date=day)
                    row['selected'] = False
        return mutate(key, payload, change)

    @app.get('/api/batches/{key}/alias-preview')
    def alias_preview(key: str):
        from .alias_bulk import preview
        return preview(load(key))

    @app.post('/api/batches/{key}/alias-commit')
    def alias_commit(key: str, payload: dict):
        from .alias_bulk import approved_indices
        def change(b):
            indices = approved_indices(b, payload.get('rows'))
            app.state.commit_batch(b, indices=indices)
        return mutate(key, payload, change)

    @app.post('/api/batches/{key}/commit')
    def commit(key: str, payload: dict):
        def change(b):
            if b.get('preview'):
                raise ValueError('历史界面预览不能入库，请上传TXT生成正式候审批次')
            if b['state'] not in ('ready', 'reviewable', 'failed'):
                raise ValueError('批次未完成解析')
            confirmations = payload.get('similar_confirmations', [])
            if not isinstance(confirmations, list) or any(not isinstance(t, str) for t in confirmations):
                raise ValueError('相似数据确认无效')
            if confirmations:
                app.state.commit_batch(b, confirmations=confirmations)
            else:
                app.state.commit_batch(b)
        return mutate(key, payload, change)

    @app.post('/api/batches/{key}/rows/{index}/commit')
    def commit_one(key: str, index: int, payload: dict):
        def change(b):
            if b.get('preview') or not b['rows']:
                raise ValueError('此批次不能入库')
            if not 0 <= index < len(b['rows']):
                raise HTTPException(404, '条目不存在')
            row = b['rows'][index]
            if row.get('imported') or row.get('already_imported'):
                return
            if eligibility_errors(row):
                raise ValueError('；'.join(eligibility_errors(row)))
            confirmations = payload.get('similar_confirmations', [])
            if not isinstance(confirmations, list) or any(not isinstance(t, str) for t in confirmations):
                raise ValueError('相似数据确认无效')
            app.state.commit_batch(b, confirmations=confirmations, index=index)
        return mutate(key, payload, change)

    @app.post('/api/url')
    def upload_url(payload: dict):
        from .url_note import fetch_note
        url, title, note = fetch_note(str(payload.get('url', '')).strip())
        content = note.encode('utf-8')
        digest = hashlib.sha256(content).hexdigest()
        folder = uploads / digest
        folder.mkdir(exist_ok=True)
        path = folder / 'url-note.txt'
        path.write_bytes(content)
        batch = store.create(title + '.txt', url)
        batch.update(source_kind='url', source_title=title)
        batch['input_path'] = 'uploads/' + digest + '/url-note.txt'
        store.write(batch)
        pool.submit(app.state.parse_job, store, batch['id'], path, dump_dir or os.environ.get('MODOU_BANGUMI_DUMP', 'data/bangumi_locale'))
        return {'id': batch['id'], 'url': '/review/' + batch['id']}

    @app.post('/api/resolve')
    def resolve_url(payload: dict):
        url = str(payload.get('url', '')).strip()
        if payload.get('kind') == 'main' or not url.startswith('https://gamefaqs.gamespot.com/'):
            candidate = subject(url)
            if payload.get('kind') == 'main':
                return {'candidate': candidate, 'main_id': str(candidate['id'])}
            candidate = hydrate_candidate(candidate, payload.get('platform'))
            from ..bangumi import english_name
            candidate['name_en'] = english_name(candidate)
            from ..main_subject import MainSubjects
            from ..bangumi import AnonymousAPI, LocalDump
            api = AnonymousAPI()
            resolution = MainSubjects(LocalDump(dump_dir or os.environ.get('MODOU_BANGUMI_DUMP', 'data/bangumi_locale')).path, api).resolve(candidate)
            from ..product_type import ProductTypes
            types = ProductTypes().resolve(candidate, resolution, raw_name=candidate.get('name', ''))
            return {'candidate': candidate, 'main_resolution': resolution, 'type_resolution': types}
        candidate = hydrate_candidate(gamefaqs(url), payload.get('platform'))
        # Deprecated 2026-11-19: resolution = suggest_main(candidate, read_config())
        resolution = {'status': 'disabled', 'main_id': candidate.get('bangumi_main'), 'interactions': []}
        from ..product_type import ProductTypes
        types = ProductTypes().resolve(candidate, resolution, raw_name=candidate.get('name', ''))
        return {'candidate': candidate, 'main_resolution': resolution, 'type_resolution': types}

    return app
