import itertools
import unittest
from task import *

class TaskChecks(unittest.TestCase):
    def test_independent_oracles_exhaustive_boundaries(self):
        for qty,stock,fragile,recalled,member,requested,region,sku in itertools.product(
            [1,2,3,4], [0,1,2,3,4], [False,True], [False,True], [False,True], ['standard','express'], REGIONS, PRICES):
            r=dict(id='ABCD',quantity=qty,stock=stock,fragile=fragile,recalled=recalled,member=member,requested=requested,region=region,sku=sku)
            self.assertEqual(oracle([r]), independent_oracle([r]))

    def test_noise_counts_and_locality(self):
        rows=dataset('train',400,9301)
        for kind in ['clean','scattered','systematic']:
            pool=corrections(rows,kind,31)
            self.assertEqual(sum(r['target'] != r['correct'] for r in pool),0 if kind=='clean' else 80)
            for r in pool:
                expected={v['id']:v for v in r['correct']['orders']}
                changed=[v['id'] for v in r['target']['orders'] if v != expected[v['id']]]
                self.assertEqual(changed,[r['focus_id']] if r['corrupted'] else [])
        for reg in REGIONS:
            self.assertEqual(sum(r['corrupted'] for r in corrections(rows,'scattered',31) if r['region']==reg),16)

    def test_scorer_and_metamorphic_properties(self):
        for row in dataset('dev',50,9302):
            self.assertEqual(score(row,canonical(row['correct']))['exact'],1)
            self.assertEqual(score(row,canonical(row['flawed']))['exact'],0)
            self.assertEqual(score(row,'not JSON')['exact'],0)
            wrong_order=copy.deepcopy(row['correct'])
            wrong_order['orders'].reverse()
            self.assertEqual(score(row,canonical(wrong_order))['decisions_exact'],1)
            self.assertEqual(score(row,canonical(wrong_order))['exact'],0)
            malformed=copy.deepcopy(row['correct'])
            malformed['orders'][0]['route']=[]
            self.assertEqual(score(row,canonical(malformed))['exact'],0)
            self.assertEqual(oracle(list(reversed(row['records']))),row['correct'])
            mutated=copy.deepcopy(row)
            mutated['records'][next(i for i,x in enumerate(mutated['records']) if x['recalled'])]['stock'] += 5
            self.assertEqual(oracle(mutated['records']),row['correct'])

    def test_splits(self):
        seen=set()
        for split,n,seed in [('train',400,9301),('dev',50,9302),('test',250,9303)]:
            rows=dataset(split,n,seed)
            keys={sha(r['records']) for r in rows}
            self.assertFalse(seen & keys)
            self.assertEqual(len(keys),n)
            seen |= keys

if __name__=='__main__': unittest.main()
