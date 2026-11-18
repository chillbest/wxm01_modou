"""Upgrade legacy review keys without rewriting stored evidence or URL values."""
def upgrade_outlinks(value):
    if isinstance(value, list):
        return [upgrade_outlinks(item) for item in value]
    if isinstance(value, dict):
        result = {key: upgrade_outlinks(item) for key, item in value.items() if key != 'gamefaqs_link'}
        if 'outlink' not in result and 'gamefaqs_link' in value:
            result['outlink'] = value['gamefaqs_link']
        return result
    if value == 'final.gamefaqs_link':
        return 'final.outlink'
    return value
