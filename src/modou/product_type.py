"""Suggest product types from the resolved main Subject only."""
from .models import GPC_TYPES


def subject_id(value):
    if type(value) is int:
        return str(value) if value > 0 else None
    if isinstance(value, str) and value.isascii() and value.isdecimal() and int(value) > 0:
        return str(int(value))
    return None


class ProductTypes:
    def resolve(self, selected, main=None, *, raw_name='', note=''):
        main = main or {}
        result = {'status': 'unknown', 'type': None, 'candidates': [],
                  'evidence': [], 'interactions': [], 'reason': '', 'errors': []}
        if not selected:
            return dict(result, reason='游戏及内容版本未确定')
        if selected.get('gpc_id') and selected.get('type') in GPC_TYPES:
            return dict(result, status='saved', type=selected['type'], reason='复用已审核GPC类型')
        sid = subject_id(selected.get('bangumi_id') or selected.get('id'))
        mid = subject_id(main.get('main_id'))
        if not sid or not mid or main.get('status') in ('unknown', 'failed', 'conflict'):
            return dict(result, reason='main或bangumi_id未确定')
        return dict(result, status='rule', type='Base' if mid == sid else '母子集',
                    reason='main与bangumi_id相同' if mid == sid else 'main与bangumi_id不同')
