"""Explicit snapshot comparisons; differences are not inferred war outcomes."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from . import country_names, data_store


def _rows(manifest, table):
    database = Path(manifest['dataset_dir']) / manifest.get('sqlite', data_store.SQLITE_NAME)
    available = {r['name'] for r in data_store.list_sqlite_tables(database)}
    if table not in available:
        return []
    return list(data_store.iter_sqlite_rows(database, table))


def _available(manifest):
    database = Path(manifest['dataset_dir']) / manifest.get('sqlite', data_store.SQLITE_NAME)
    return {r['name'] for r in data_store.list_sqlite_tables(database)}


def compare(first, second):
    a, b = first['source'], second['source']
    lines = ['# 存档历史对照', '',
             f"- 起点：{a['country']}，{a['date']}；来源：{Path(a['path']).name}",
             f"- 终点：{b['country']}，{b['date']}；来源：{Path(b['path']).name}",
             '- 以下为两个所选存档的记录差异。日期之间的具体过程与原因，需要存档内的事件证据。',
             '- 请比较同一局游戏的存档。未导出的国家或字段不能视为灭亡或数值为零。', '',
             '## 国家经济与人口', '', '| 国家 | 指标 | 起点 | 终点 |', '|---|---|---:|---:|']
    first_tables, second_tables = _available(first), _available(second)
    old = {r['tag']: r for r in _rows(first, 'major_countries')}
    new = {r['tag']: r for r in _rows(second, 'major_countries')}
    def label(tag):
        row = new.get(tag) or old.get(tag) or {}
        return row.get('country_name') or country_names.display_name(tag)
    for tag in sorted(old.keys() & new.keys()):
        for field, name in [('gdp', 'GDP'), ('population', '人口'), ('sol', '生活水平'), ('literacy', '识字率')]:
            before, after = old[tag].get(field, ''), new[tag].get(field, '')
            if before != after:
                lines.append(f'| {label(tag)} | {name} | {before or "未记录"} | {after or "未记录"} |')
    for title, tags in [('只在起点国家表出现', old.keys() - new.keys()), ('只在终点国家表出现', new.keys() - old.keys())]:
        lines.extend(['', title + '：' + ('、'.join(label(t) for t in sorted(tags)) or '无')])
    lines.extend(['', '## 地区归属差异', '', '| 地区 | 起点归属 | 终点归属 |', '|---|---|---|'])
    def ownership(manifest):
        result = defaultdict(set)
        for row in _rows(manifest, 'states'):
            result[row.get('region') or row['state_id']].add(row.get('tag', ''))
        return result
    previous, current = ownership(first), ownership(second)
    for region in sorted(previous.keys() & current.keys()):
        if previous[region] != current[region]:
            lines.append(f"| {region} | {'、'.join(label(t) for t in sorted(previous[region]))} | {'、'.join(label(t) for t in sorted(current[region]))} |")
    for title, table, fields in [
        ('附属关系', 'subject_relations', ('overlord_tag', 'subject_tag', 'type')),
        ('法律', 'laws', ('tag', 'law')),
        ('市场成员关系', 'market_members', ('tag', 'market_owner_tag')),
        ('正式条约', 'treaties', ('treaty_id', 'first_tag', 'second_tag', 'name_type', 'entered_into_force_on')),
        ('条约条款', 'treaty_articles', ('treaty_id', 'article', 'source_tag', 'target_tag', 'goods', 'quantity')),
        ('政治运动', 'political_movements', ('tag', 'movement_id', 'identity_type', 'ideology', 'radicalism')),
        ('已记录战争', 'wars', ('war_id', 'start_date', 'peace_date', 'participant_tags')),
    ]:
        if table not in first_tables or table not in second_tables:
            missing = '、'.join(name for name, available in [('起点', first_tables), ('终点', second_tables)] if table not in available)
            lines.extend(['', '## ' + title, '', f'{missing}存档的导出包未提供该表，无法比较。'])
            continue
        before = {tuple(r.get(k, '') for k in fields) for r in _rows(first, table)}
        after = {tuple(r.get(k, '') for k in fields) for r in _rows(second, table)}
        lines.extend(['', '## ' + title, '', '| 记录变化 | 内容 |', '|---|---|'])
        for kind, values in [('只在起点记录', before - after), ('只在终点记录', after - before)]:
            for value in sorted(values):
                cells = []
                for field, item in zip(fields, value):
                    cells.append('、'.join(label(t) for t in item.split(';')) if field.endswith('tag') or field.endswith('tags') else item)
                lines.append(f"| {kind} | {'；'.join(cells)} |")
    return '\n'.join(lines) + '\n'


def _source_title(manifest):
    source = manifest.get('source', {})
    return f"{source.get('country', '未知国家')} {source.get('date', '未知日期')}"


def _source_date(manifest):
    source = manifest.get('source', {})
    return str(source.get('game_date') or source.get('date') or '')


def _country_rows(manifest):
    return {r.get('tag', ''): r for r in _rows(manifest, 'major_countries') if r.get('tag')}


def _simple_relation_set(manifest, table, fields):
    return {tuple(row.get(field, '') for field in fields) for row in _rows(manifest, table)}


def timeline(manifests):
    """Build an explicit multi-snapshot timeline. It reports observed changes only."""
    ordered = sorted(manifests, key=_source_date)
    lines = [
        '# 战役时间线对照',
        '',
        f'- 存档数量：{len(ordered)}',
        '- 本文只记录多个已选择存档之间能直接观察到的变化，不自动推断战争原因、胜负或历史缺口。',
        '- 请只把同一局游戏的存档放在一起比较；不同战役同名国家不能视为连续历史。',
        '',
        '## 时间点',
        '',
        '| 序号 | 国家 | 游戏日期 | 来源文件 |',
        '|---:|---|---|---|',
    ]
    for index, manifest in enumerate(ordered, 1):
        source = manifest.get('source', {})
        lines.append(f"| {index} | {source.get('country', '未知国家')} | {source.get('date', '未知日期')} | {Path(source.get('path', '')).name} |")

    if len(ordered) < 2:
        return '\n'.join(lines) + '\n'

    lines.extend(['', '## 相邻变化摘要', ''])
    for index in range(1, len(ordered)):
        first, second = ordered[index - 1], ordered[index]
        old, new = _country_rows(first), _country_rows(second)
        lines.extend(['', f"### {_source_title(first)} → {_source_title(second)}", ''])
        metric_changes = []
        for tag in sorted(old.keys() & new.keys()):
            label = new[tag].get('country_name') or old[tag].get('country_name') or country_names.display_name(tag)
            changes = []
            for field, name in [('gdp', 'GDP'), ('population', '人口'), ('sol', '生活水平'), ('literacy', '识字率')]:
                before, after = old[tag].get(field, ''), new[tag].get(field, '')
                if before != after:
                    changes.append(f"{name} {before or '未记录'}→{after or '未记录'}")
            if changes:
                metric_changes.append(f"- {label}：" + "；".join(changes))
        lines.extend(metric_changes[:30] or ['- 主要国家指标未读到明显变化。'])

        state_before = defaultdict(set)
        state_after = defaultdict(set)
        for row in _rows(first, 'states'):
            state_before[row.get('region') or row.get('state_id', '')].add(row.get('country_name') or country_names.display_name(row.get('tag', '')))
        for row in _rows(second, 'states'):
            state_after[row.get('region') or row.get('state_id', '')].add(row.get('country_name') or country_names.display_name(row.get('tag', '')))
        changed_regions = [
            (region, state_before[region], state_after[region])
            for region in sorted(state_before.keys() & state_after.keys())
            if state_before[region] != state_after[region]
        ]
        lines.extend(['', '地区归属变化：'])
        if changed_regions:
            for region, before, after in changed_regions[:40]:
                lines.append(f"- {region}：{'、'.join(sorted(before))} → {'、'.join(sorted(after))}")
        else:
            lines.append('- 未读到地区归属变化。')

        relation_specs = [
            ('附属关系', 'subject_relations', ('overlord_tag', 'subject_tag', 'type')),
            ('市场成员', 'market_members', ('tag', 'market_owner_tag')),
            ('正式条约', 'treaties', ('treaty_id', 'first_tag', 'second_tag', 'name_type')),
            ('政治运动', 'political_movements', ('tag', 'movement_id', 'identity_type', 'ideology')),
            ('战争记录', 'wars', ('war_id', 'start_date', 'peace_date', 'participant_tags')),
        ]
        for title, table, fields in relation_specs:
            first_tables, second_tables = _available(first), _available(second)
            lines.extend(['', f'{title}变化：'])
            if table not in first_tables or table not in second_tables:
                lines.append('- 有时间点缺少该表，无法比较。')
                continue
            before = _simple_relation_set(first, table, fields)
            after = _simple_relation_set(second, table, fields)
            diff = [('新增', value) for value in sorted(after - before)] + [('移除', value) for value in sorted(before - after)]
            if not diff:
                lines.append('- 未读到变化。')
                continue
            for kind, value in diff[:40]:
                rendered = []
                for field, item in zip(fields, value):
                    rendered.append('、'.join(country_names.display_name(t) for t in item.split(';')) if field.endswith('tag') or field.endswith('tags') else item)
                lines.append(f"- {kind}：" + "；".join(rendered))
    return '\n'.join(lines) + '\n'
