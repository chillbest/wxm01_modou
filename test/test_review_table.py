from modou.review_table import render_review, stage_hits


def row():
    return {'raw_name': '游戏', 'extracted': {'raw_line': '🔸游戏｜HK100'},
            'quote': {'platform': 'PS5', 'region': '港版', 'lowprice_cny': '100', 'lowprice_date': '2026-11-03', 'lowprice_method': '直接购买'},
            'stage_hits': {'local': {'id': 4, 'name_cn': '游戏'}}, 'errors': []}


def test_merged_rows_link_and_no_problem():
    html = render_review([row()])
    assert html.count('colspan="7"') == 0
    assert '（1）🔸游戏｜HK100' in html
    assert html.count('<table style=') == 2
    assert html.count('table-layout:fixed') == 2
    assert html.count('<colgroup>') == 2
    assert html.count('<col style="width:7%">') == 2
    assert html.count('<thead>') == 1
    assert html.count('<th>') == 7
    assert '<th>序号</th>' not in html
    assert '从原文提取的名称' not in html
    assert html.count('<col style=') == 14
    assert 'https://bgm.tv/subject/4' in html
    assert '<td>-</td>' in html
    assert '——' not in html


def test_short_and_long_problems_escape():
    r = row(); r['errors'] = ['1234567890']
    assert '——' not in render_review([r])
    r['errors'] = ['12345678901', '<script>']
    result = render_review([r])
    assert result.count('colspan="7"') == 1
    assert '——' in result and '<br>' in result
    assert '&lt;script&gt;' in result


def test_legacy_api_candidate_is_only_ds_hit():
    r = {'source': 'api', 'candidates': [{'id': 4, 'name_cn': '游戏'}], 'suggestion': {'bangumi_id': 4}}
    assert set(stage_hits(r)) == {'ds'}


def test_unspecified_edition_has_no_version_warning():
    result = render_review([row()])
    assert '版本待确认' not in result


def test_numbering_survives_separate_tables():
    html = render_review([row(), row(), row()])
    for index in range(1, 4):
        assert '（' + str(index) + '）' in html


def test_quote_platform_rules():
    from modou.review_table import quote_platform
    r = row()
    assert quote_platform(r) == 'PS5'
    r['stage_hits']['local']['infobox'] = [{'key':'平台','value':[{'v':'PS4'},{'v':'PC'}]}]
    assert quote_platform(r) == 'PS4'
    r['stage_hits']['local']['infobox'][0]['value'].append({'v':'PS5'})
    assert quote_platform(r) == 'PS5'
    r['extracted']['raw_name'] = '游戏 PS4'
    assert quote_platform(r) == 'PS4'
    r['extracted']['raw_name'] = '游戏'
    r['stage_hits']['local']['infobox'] = '{{Infobox Game\n|平台= PS4、PC\n|发行日期= 2020\n}}'
    assert quote_platform(r) == 'PS4'
    r['stage_hits']['local']['infobox'] = []
    assert quote_platform(r) == 'PS5'



def test_ps_disc_selected_platform_matrix():
    from modou.review_table import quote_platform
    for stage in ('local', 'api', 'ds', 'alias', 'gamefaqs'):
        for platforms, expected, explicit_expected in [(['PS4','PS5'], 'PS5', 'PS4'), (['PS4'], 'PS4', 'PS4'), (['PS5'], 'PS5', 'PS5'), (['PC'], None, None)]:
            r = row()
            r['ps_disc_filter'] = True
            r['stage_hits'] = {stage: {'platforms': platforms}}
            assert quote_platform(r) == expected
            r['extracted']['raw_name'] = '游戏 PS4'
            assert quote_platform(r) == explicit_expected
    r['extracted']['raw_name'] = '游戏'
    r['stage_hits'] = {'gamefaqs': {'outlink': 'https://gamefaqs.gamespot.com/ps4/1-game'}}
    assert quote_platform(r) == 'PS4'
    r['stage_hits']['gamefaqs']['platforms'] = ['PS4','PS5']
    assert quote_platform(r) == 'PS5'



def test_no_match_has_no_default_platform():
    from modou.review_table import quote_platform
    r = row(); r['stage_hits'] = {}
    assert quote_platform(r) is None
    r['extracted']['raw_name'] = '游戏 PS4'
    assert quote_platform(r) is None
