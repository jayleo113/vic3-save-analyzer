"""Extract world modules once, then select country views without rescanning."""
from __future__ import annotations

import hashlib
import json
import time

from .snapshot_store import SnapshotStore, extraction_version
from .fingerprint import text_hash


def collect(a, txt, full_pops, mark):
    digest = text_hash(txt)
    names_hash = text_hash(json.dumps(a.COUNTRY_NAMES, sort_keys=True, ensure_ascii=False))
    store = SnapshotStore(a.TOOL_DIR / 'data_cache', digest, extraction_version(a.TOOL_DIR) + names_hash)
    timings = {}
    hits = []
    cross_hits = []
    context = {}
    metadata = a.meta(txt)
    environment = json.dumps([metadata.get('version'), metadata.get('mods'), a.COUNTRY_NAMES], sort_keys=True, ensure_ascii=False)
    blocks = {
        'countries': ['country_manager'], 'cultures': ['cultures'], 'states': ['states'],
        'buildings': ['building_manager'], 'population': ['pops'],
        'groups': ['interest_groups'], 'technology': ['technology'], 'relations': ['relations'],
        'pacts': ['pacts'], 'treaties': ['treaty_manager', 'treaty_article_manager'],
        'companies': ['companies'], 'movements': ['political_movement_manager'],
        'wars': ['war_manager'], 'plays': ['diplomatic_plays'], 'goals': ['war_goal_manager'],
        'military': ['military_formation_manager'], 'battles_full': ['battle_manager'], 'battles_lite': ['battle_manager'],
    }

    def signature(name):
        # Unlisted parsers may search outside managers, so reuse only the exact snapshot.
        if name not in blocks:
            return digest
        h = hashlib.sha256(environment.encode('utf-8'))
        for manager in blocks[name]:
            block = a.database_block(txt, manager)
            h.update(manager.encode('ascii') + b'\x00')
            h.update(text_hash(block).encode('ascii') if block is not None else b'absent')
        if name not in {'countries', 'cultures'}:
            h.update(context['tags'].encode('ascii'))
        if name in {'buildings', 'population'}:
            h.update(context['owners'].encode('ascii'))
        if name in {'population', 'battles_full'}:
            h.update(context['cultures'].encode('ascii'))
        return h.hexdigest()

    def context_hash(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()

    def stage(name, percent, label, function):
        mark(percent, label)
        started = time.perf_counter()
        result = store.get(name)
        dependency = None
        if result is None:
            dependency = signature(name)
            result = store.get(name, dependency)
            if result is not None:
                cross_hits.append(name)
        if result is None:
            result = function()
            store.put(name, result, dependency)
        else:
            hits.append(name)
        timings[name] = round(time.perf_counter() - started, 4)
        return result

    try:
        countries = stage('countries', 5, '读取国家', lambda: a.parse_countries(txt))
        countries = {int(k): v for k, v in countries.items()}
        context['tags'] = context_hash({k: v.get('tag', '') for k, v in countries.items()})
        ids = set(countries)
        rankings = stage('rankings', 10, '读取国家排名', lambda: a.parse_rankings(txt, countries))
        all_states, owners = stage('states', 12, '读取地区', lambda: a.parse_all_states(txt, countries))
        owners = {int(k): v for k, v in owners.items()}
        context['owners'] = context_hash(owners)
        rows = {}

        def tables(name, percent, label, names, function):
            result = stage(name, percent, label, function)
            values = [result] if len(names) == 1 else result
            rows.update(zip(names, values))

        tables('buildings', 20, '读取建筑', ['building_details', 'building_summary'],
               lambda: a.parse_buildings_for_countries(txt, owners, countries, ids))
        cultures = stage('cultures', 28, '读取文化', lambda: a.parse_culture_map(txt)) if full_pops else {}
        context['cultures'] = context_hash(cultures)
        pop_names = ['pop_summary', 'pop_by_type', 'pop_by_culture', 'pop_by_religion']
        if full_pops:
            tables('population', 30, '读取人口', pop_names,
                   lambda: a.parse_pops_for_countries(txt, owners, countries, ids, cultures,
                       progress=lambda p, label: mark(30 + int(p * .28), label)))
        else:
            rows.update({name: [] for name in pop_names})
        definitions = [
            ('laws', 58, '法律', ['law_rows'], lambda: a.parse_laws_for_countries(txt, countries, ids)),
            ('groups', 60, '利益集团', ['ig_rows'], lambda: a.parse_interest_groups_for_countries(txt, countries, ids)),
            ('technology', 63, '科技', ['tech_rows'], lambda: a.parse_technology_for_countries(txt, countries, ids)),
            ('relations', 68, '外交关系', ['relation_rows'], lambda: a.parse_relations_for_countries(txt, countries, ids)),
            ('pacts', 70, '附属关系', ['pact_rows'], lambda: a.parse_pacts_for_countries(txt, countries, ids)),
            ('treaties', 71, '条约', ['treaty_rows', 'treaty_article_rows'], lambda: a.parse_treaties_for_countries(txt, countries, ids)),
            ('markets', 72, '市场', ['market_rows', 'market_member_rows', 'market_state_rows', 'market_trade_goods_rows'], lambda: a.parse_market_data(txt, countries, all_states)),
            ('companies', 73, '公司', ['company_rows'], lambda: a.parse_companies_for_countries(txt, countries, ids)),
            ('movements', 74, '政治运动', ['political_movement_rows'], lambda: a.parse_political_movements_for_countries(txt, countries, ids)),
            ('wars', 75, '战争', ['war_rows', 'war_participant_rows'], lambda: a.parse_wars_for_countries(txt, countries, ids)),
            ('plays', 76, '外交博弈', ['diplomatic_play_rows', 'war_cost_rows'], lambda: a.parse_diplomatic_plays_for_countries(txt, countries, ids)),
            ('goals', 77, '战争目标', ['war_goal_rows'], lambda: a.parse_war_goals_for_countries(txt, countries, ids)),
            ('military', 78, '军队', ['military_formation_rows'], lambda: a.parse_military_formations_for_countries(txt, countries, ids)),
            ('battles_' + ('full' if full_pops else 'lite'), 79, '战斗', ['battle_rows', 'battle_casualty_rows'], lambda: a.parse_battles_for_countries(txt, countries, ids, cultures, progress=lambda p, label: mark(79 + int(p * .03), label))),
        ]
        for name, percent, label, names, function in definitions:
            tables(name, percent, '读取' + label, names, function)
        return countries, rankings, all_states, rows, {'snapshot': digest, 'stages': timings, 'reused_modules': hits, 'cross_snapshot_modules': cross_hits}
    finally:
        store.close()


def select(rows, ids, countries, a):
    """Keep cross-country records together while deriving a selected view."""
    chosen = {str(i) for i in ids}
    tags = {countries[i]['tag'] for i in ids}

    def any_id(row, *fields):
        return any(str(row.get(field, '')) in chosen for field in fields)

    output = {}
    special = {'treaty_rows', 'treaty_article_rows', 'war_rows', 'diplomatic_play_rows', 'war_goal_rows', 'battle_rows'}
    for name, values in rows.items():
        if name in special:
            continue
        output[name] = values if name.startswith('market_') else [r for r in values if any_id(r, 'country_id')]
    treaty_ids = {r['treaty_id'] for r in rows['treaty_rows'] if any_id(r, 'first_country_id', 'second_country_id')}
    treaty_ids.update(r['treaty_id'] for r in rows['treaty_article_rows'] if any_id(r, 'first_country_id', 'second_country_id', 'source_country_id', 'target_country_id'))
    for name in ('treaty_rows', 'treaty_article_rows'):
        output[name] = [r for r in rows[name] if r['treaty_id'] in treaty_ids]
    output['war_rows'] = []
    for original in rows['war_rows']:
        involved = [i for i in original['participant_country_ids'].split(';') if i in chosen]
        if not involved:
            for field in ('attacker_peace_country', 'defender_peace_country'):
                if original[field] in tags:
                    involved = [str(i) for i in ids if countries[i]['tag'] == original[field]][:1]
                    break
        if involved:
            row = dict(original)
            row['major_country_ids'] = ';'.join(involved)
            row['major_tags'] = ';'.join(countries[int(i)]['tag'] for i in involved)
            output['war_rows'].append(row)
    output['diplomatic_play_rows'] = [r for r in rows['diplomatic_play_rows'] if
        any_id(r, 'initiator_id', 'target_id') or any(set(r.get(field, '').split(';')) & tags for field in ('initiator_side_tags', 'target_side_tags', 'involved_tags'))]
    play_ids = {r['diplomatic_play'] for r in output['diplomatic_play_rows']}
    output['war_cost_rows'] = [r for r in output['war_cost_rows'] if r['diplomatic_play'] in play_ids]
    output['war_goal_rows'] = [r for r in rows['war_goal_rows'] if any_id(r, 'holder_id', 'creator_id', 'target_country_id')]
    output['battle_rows'] = [r for r in rows['battle_rows'] if any_id(r, 'attacker_country_id', 'defender_country_id')]
    output['subject_rows'] = a.parse_subject_relations(output['pact_rows'], countries)
    return output
