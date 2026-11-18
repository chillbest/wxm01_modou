"""Bind alias-only bulk approval to the exact saved preview."""
import hashlib
import json

from .service import alias_bound, public_batch
from .store import Conflict, persisted
from ..web_review import eligibility_errors


def eligible(row):
    return (not row.get('imported') and not row.get('already_imported')
            and alias_bound(row) and not eligibility_errors(row))


def preview(batch):
    if batch.get('preview') or batch.get('state') not in ('ready', 'reviewable', 'failed'):
        raise ValueError('此批次暂不能批量入库')
    public = public_batch(batch)
    # The GET refresh attaches proposed_inserts, but Store deliberately omits
    # that derived field. Hash the same persistent representation on both paths.
    snapshot_rows = persisted(public)['rows']
    rows = []
    for index, row in enumerate(public['rows']):
        if not eligible(row):
            continue
        snapshot = json.dumps({'batch': batch['id'], 'index': index, 'row': snapshot_rows[index]},
                              ensure_ascii=False, sort_keys=True, default=str)
        rows.append({'index': index, 'token': hashlib.sha256(snapshot.encode()).hexdigest(), 'row': row})
    return {'revision': batch['revision'], 'rows': rows}


def approved_indices(batch, submitted):
    current = preview(batch)
    expected = [{'index': item['index'], 'token': item['token']} for item in current['rows']]
    if not expected:
        raise Conflict('没有符合条件的条目，请关闭并重新打开预览')
    if submitted != expected:
        raise Conflict('预览条目已变化，请关闭并重新打开预览')
    return [item['index'] for item in expected]
