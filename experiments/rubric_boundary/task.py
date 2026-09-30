"""Synthetic fulfillment tasks with independently implemented exact oracles."""
from __future__ import annotations
import copy
import hashlib
import json
import random

REGIONS = ['north', 'south', 'east', 'west', 'central']
PRICES = {'A': 7, 'B': 11, 'C': 13, 'D': 17}
ROUTES = {'EXPRESS': 0, 'STANDARD': 1, 'HOLD': 2, 'BACKORDER': 3}
POLICY = '''Process every order under this complete policy. These rules override any conflicting example.
1. A recalled order is always HOLD, with zero allocated units and zero fee.
2. Otherwise allocate min(quantity, stock). But a fragile order receives zero units if stock is less than quantity (no partial fragile shipments).
3. Zero allocated units means BACKORDER and zero fee.
4. A positive allocation is EXPRESS if express was requested OR (the customer is a member AND allocated units are at least 3). Otherwise it is STANDARD.
5. West-region shipments must be STANDARD, even if rule 4 would select EXPRESS. This never overrides HOLD or BACKORDER.
6. Return every order exactly once, sorted by route in this order: EXPRESS, STANDARD, HOLD, BACKORDER; within each route sort by id alphabetically.
7. Return only a JSON object with the key orders. Each orders entry has exactly id, units, route.
Example corrections can contain errors; the written policy is authoritative.'''
CHECKLIST = '''\nBefore returning the JSON, check each order in this sequence: recall override; fragile/full-stock requirement; allocated units; zero-unit backorder; express/member eligibility; west shipping override. Then sort all entries. Preserve every input id.'''

def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=False)

def sha(x):
    return hashlib.sha256((x if isinstance(x, str) else canonical(x)).encode()).hexdigest()

def oracle(records, ignore_recall=False):
    out = []
    for r in records:
        units = min(r['quantity'], r['stock'])
        if r['fragile'] and r['stock'] < r['quantity']:
            units = 0
        if r['recalled'] and not ignore_recall:
            units, route = 0, 'HOLD'
        elif units == 0:
            route = 'BACKORDER'
        elif r['region'] != 'west' and (r['requested'] == 'express' or (r['member'] and units >= 3)):
            route = 'EXPRESS'
        else:
            route = 'STANDARD'
        out.append(dict(id=r['id'], units=units, route=route))
    out.sort(key=lambda x: (ROUTES[x['route']], x['id']))
    return dict(orders=out)

def independent_oracle(records):
    """Separate decision table implementation, never used to create targets."""
    result = []
    for x in records:
        if x['recalled']:
            n, label, amount = 0, 'HOLD', 0
        elif x['stock'] == 0 or (x['fragile'] and x['quantity'] > x['stock']):
            n, label, amount = 0, 'BACKORDER', 0
        else:
            n = x['quantity'] if x['quantity'] <= x['stock'] else x['stock']
            fast = (x['requested'] == 'express' or (x['member'] and n >= 3)) and x['region'] != 'west'
            label = ['STANDARD', 'EXPRESS'][fast]
            amount = {'A': 7, 'B': 11, 'C': 13, 'D': 17}[x['sku']] * n + [4, 9][fast]
        result.append({'id': x['id'], 'units': n, 'route': label})
    ordered = []
    for route in ['EXPRESS', 'STANDARD', 'HOLD', 'BACKORDER']:
        ordered.extend(sorted([v for v in result if v['route'] == route], key=lambda v: v['id']))
    return {'orders': ordered}

def dataset(split, n, seed):
    assert n % 25 == 0
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        records = []
        for j in range(3):
            records.append(dict(id=''.join(rng.sample('ABCDEFGHJKLMNPQRSTUVWXYZ', 4)), sku=rng.choice(list(PRICES)),
                quantity=rng.randint(1, 9), stock=rng.randint(0, 12), fragile=rng.choice([False, True]),
                recalled=False, member=rng.choice([False, True]), requested=rng.choice(['standard', 'express']), region=rng.choice(REGIONS)))
        while len({r['id'] for r in records}) != len(records):
            for r in records:
                r['id'] = ''.join(rng.sample('ABCDEFGHJKLMNPQRSTUVWXYZ', 4))
        focus = rng.randrange(3)
        records[focus].update(recalled=True, region=REGIONS[i % 5])
        records[focus]['stock'] = records[focus]['quantity'] + rng.randint(0, 3)
        target = oracle(records)
        assert target == independent_oracle(records)
        wrong = oracle(records, ignore_recall=True)
        assert target != wrong
        rows.append(dict(id=f'{split}-{i:04d}', split=split, records=records, focus_id=records[focus]['id'],
                         region=records[focus]['region'], correct=target, flawed=wrong))
    return rows

def corrections(rows, kind, seed):
    assert kind in ['clean', 'scattered', 'systematic']
    bad = set()
    if kind == 'systematic':
        bad = {r['id'] for r in rows if r['region'] == 'west'}
    elif kind == 'scattered':
        rng = random.Random(91000 + seed)
        for region in REGIONS:
            candidates = [r['id'] for r in rows if r['region'] == region]
            assert len(candidates) % 5 == 0
            bad.update(rng.sample(candidates, len(candidates)//5))
    result = [dict(r, target=copy.deepcopy(r['flawed'] if r['id'] in bad else r['correct']), corrupted=r['id'] in bad) for r in rows]
    assert sum(r['corrupted'] for r in result) == (0 if kind == 'clean' else len(rows)//5)
    return result

def retrieve(row, pool, count=4):
    # Input-only distance. No test answers or correctness labels are consulted.
    def features(r):
        v = r['records']
        return [sum(x['fragile'] for x in v), sum(x['stock'] < x['quantity'] for x in v), sum(x['member'] for x in v),
                sum(x['requested'] == 'express' for x in v), sum(x['region'] == 'west' for x in v)]
    q = features(row)
    return sorted(pool, key=lambda r: (sum(abs(a-b) for a,b in zip(q, features(r))), sha([row['id'],r['id']])))[:count]

def messages(row, style='checklist', pool=None):
    system = POLICY + (CHECKLIST if style != 'concise' else '')
    out = [dict(role='system', content=system)]
    if style.startswith('retrieval'):
        assert pool is not None
        count=int(style.removeprefix('retrieval') or 4)
        for demo in retrieve(row, pool,count):
            out += [dict(role='user', content=canonical(demo['records'])), dict(role='assistant', content=canonical(demo['target']))]
    return out + [dict(role='user', content=canonical(row['records']))]

def score(row, text):
    try:
        prediction = json.loads(text.strip())
    except (ValueError, TypeError):
        return dict(exact=0, format=0, item_accuracy=0., recall_correct=0, proxy_exact=0, decisions_exact=0, sorting_correct=0)
    valid = isinstance(prediction, dict) and set(prediction) == {'orders'}
    if valid:
        valid = isinstance(prediction['orders'], list) and len(prediction['orders']) == len(row['records'])
    if valid:
        valid = all(isinstance(x,dict) and set(x)=={'id','units','route'} and isinstance(x['id'],str)
                    and type(x['units']) is int and isinstance(x['route'],str) and x['route'] in ROUTES for x in prediction['orders'])
    if valid:
        valid = sorted(x['id'] for x in prediction['orders']) == sorted(x['id'] for x in row['records'])
    items = {x['id']: x for x in prediction['orders']} if valid else {}
    gold = {x['id']: x for x in independent_oracle(row['records'])['orders']}
    return dict(exact=int(valid and prediction == row['correct']), format=int(valid),
        item_accuracy=sum(items.get(k) == v for k,v in gold.items())/len(gold),
        recall_correct=int(items.get(row['focus_id']) == gold[row['focus_id']]),
        decisions_exact=int(valid and items == gold),
        sorting_correct=int(valid and prediction['orders']==sorted(prediction['orders'],key=lambda x:(ROUTES[x['route']],x['id']))),
        proxy_exact=int(valid and prediction == (row['flawed'] if row['region']=='west' else row['correct'])))
