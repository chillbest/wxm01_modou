"""Evidence-based main subject suggestions, independent of product matching."""
import json
import zipfile
from functools import lru_cache
from pathlib import Path


def classify(sid, edges):
    sid = str(sid)
    parents = {str(b) for a, b in edges if str(a) == sid}
    children = {str(a) for a, b in edges if str(b) == sid and str(a) != sid}
    if len(parents) > 1 or (parents and parents != {sid} and children):
        return {'status': 'conflict', 'subject_id': sid, 'main_id': None}
    if parents:
        parent = next(iter(parents))
        if parent != sid and (parent, sid) in {(str(a), str(b)) for a, b in edges}:
            return {'status': 'conflict', 'subject_id': sid, 'main_id': None}
        return {'status': 'self' if parent == sid else 'parent', 'subject_id': sid, 'main_id': parent}
    return {'status': 'self' if children else 'unknown', 'subject_id': sid,
            'main_id': sid if children else None}


class MainSubjects:
    def __init__(self, dump, api):
        self.api = api
        if isinstance(dump, (str, Path)):
            path = Path(dump).resolve()
            stamp = path.stat()
            self.edges = cached_edges(str(path), stamp.st_mtime_ns, stamp.st_size)
        else:
            self.edges = read_edges(dump)

    def resolve(self, selected):
        if selected.get('gpc_id') and 'bangumi_main' in selected and selected['bangumi_main'] is None:
            return {'status': 'saved', 'main_id': None, 'source': 'saved', 'explicit_null': True}
        sid = selected.get('id') or selected.get('bangumi_id')
        if not sid:
            return {'status': 'unknown', 'main_id': None}
        if selected.get('bangumi_main') and '|' in selected['bangumi_main']:
            from .main_ids import normalize_main
            return {'status': 'saved', 'main_id': normalize_main(selected['bangumi_main']), 'source': 'saved',
                    'relation': 'equal' if selected.get('type') == '合集' else 'unspecified'}
        if selected.get('bangumi_main'):
            return dict(classify(sid, [(sid, selected['bangumi_main'])]), source='saved')
        result = classify(sid, self.edges)
        result.update(source='local', evidence=[list(e) for e in sorted(self.edges) if str(sid) in e])
        if result['status'] != 'unknown':
            return result
        try:
            relations = self.api.request('/v0/subjects/' + str(sid) + '/subjects')
            edges = set()
            for row in relations:
                if row.get('relation') == '主版本':
                    edges.add((str(sid), str(row['id'])))
                elif row.get('relation') == '不同版本':
                    reverse = self.api.request('/v0/subjects/' + str(row['id']) + '/subjects')
                    if any(str(r.get('id')) == str(sid) and r.get('relation') == '主版本' for r in reverse):
                        edges.add((str(row['id']), str(sid)))
            result = classify(sid, edges)
            result.update(source='api', evidence=[list(e) for e in sorted(edges)])
            if result['status'] == 'unknown':
                result.update(status='default_self', main_id=str(sid), reason='未找到主版本，默认自身')
        except Exception:
            result.update(status='failed', reason='主版本关联API失败，待人工审核')
        return result


def read_edges(dump):
    edges = set()
    with zipfile.ZipFile(dump) as archive:
        if 'subject-relations.jsonlines' in archive.namelist():
            with archive.open('subject-relations.jsonlines') as stream:
                for line in stream:
                    row = json.loads(line)
                    if row.get('relation_type') == 4017:
                        edges.add((str(row['subject_id']), str(row['related_subject_id'])))
    return frozenset(edges)


@lru_cache(maxsize=4)
def cached_edges(path, modified_ns, size):
    return read_edges(path)
