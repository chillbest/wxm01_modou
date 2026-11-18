"""Atomic disk drafts. A revision binds approval to exactly the saved fields."""
import copy
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from ..outlinks import upgrade_outlinks


class Conflict(ValueError):
    pass


def persisted(value):
    value = copy.deepcopy(value)
    for row in value['rows']:
        row.pop('proposed_inserts', None)
    return value


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._number_legacy_batches()

    def path(self, key):
        if not re.fullmatch('(?:[a-f0-9]{8}|[a-f0-9]{32})', key):
            raise ValueError('批次编号无效')
        return self.root / (key + '.json')

    def read(self, key):
        with self.lock:
            return upgrade_outlinks(json.loads(self.path(key).read_text(encoding='utf-8')))

    def write(self, value):
        with self.lock:
            value = persisted(value)
            path = self.path(value['id'])
            temp = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
            with temp.open('x', encoding='utf-8') as stream:
                json.dump(value, stream, ensure_ascii=False, default=str)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)

    def list(self):
        with self.lock:
            return sorted((self.read(p.stem) for p in self.root.glob('*.json')),
                          key=lambda b: (b.get('batch_order', 0), b['id']))

    def _number_legacy_batches(self):
        # No historical parse timestamps are inferred from filesystem metadata.
        paths = sorted(self.root.glob('*.json'), key=lambda p: (getattr(p.stat(), 'st_birthtime', p.stat().st_mtime), p.name))
        batches = [self.read(p.stem) for p in paths]
        used = {}
        orders = {b['batch_order'] for b in batches if 'batch_order' in b}
        for batch in batches:
            if 'upload_index' in batch:
                used.setdefault(batch['filename'].casefold(), set()).add(batch['upload_index'])
        for batch in batches:
            changed = False
            numbers = used.setdefault(batch['filename'].casefold(), set())
            if 'upload_index' not in batch:
                number = 1
                while number in numbers:
                    number += 1
                batch['upload_index'] = number
                numbers.add(number)
                changed = True
            if 'batch_order' not in batch:
                order = 1
                while order in orders:
                    order += 1
                batch['batch_order'] = order
                orders.add(order)
                changed = True
            if changed:
                self.write(batch)

    def create(self, filename, source_path):
        with self.lock:
            batches = self.list()
            key = uuid.uuid4().hex[:8]
            while self.path(key).exists():
                key = uuid.uuid4().hex[:8]
            number = max((b.get('upload_index', 1) for b in batches if b['filename'].casefold() == filename.casefold()), default=0) + 1
            value = dict(id=key, revision=0, filename=filename, source_path=source_path,
                         state='queued', rows=[], error=None, upload_index=number,
                         batch_order=max((b.get('batch_order', 0) for b in batches), default=0) + 1,
                         created_at=datetime.now(timezone.utc).isoformat())
            self.write(value)
            return value

    def update(self, key, revision, mutate):
        with self.lock:
            value = self.read(key)
            if value['revision'] != revision:
                raise Conflict('页面版本已过期，请刷新后重试')
            updated = copy.deepcopy(value)
            mutate(updated)
            updated['revision'] += 1
            self.write(updated)
            return updated


def display_filename(batch):
    filename = batch.get('filename', '')
    number = batch.get('upload_index', 1)
    if batch.get('source_kind') == 'url' or str(batch.get('source_path', '')).startswith(('http://', 'https://')):
        filename = 'url：' + (batch.get('source_title') or filename.removesuffix('.txt'))
    return filename + (f'（{number}）' if number > 1 else '')
