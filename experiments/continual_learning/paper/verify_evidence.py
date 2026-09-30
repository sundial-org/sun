"""Offline evidence checks, independent arithmetic, and transcript replay.

Does not import the experiment's statistical analysis or contact any provider.
The frozen tool interpreter is reused for replay. This checks measurement
consistency, not the literary or linguistic validity of the planted rubric.
"""
from collections import Counter, defaultdict
from fractions import Fraction
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
E = HERE / 'evidence'


def read(name):
    return json.loads((E / name).read_text())


def load_groups(name, key='evaluation'):
    groups = defaultdict(list)
    with gzip.open(E / name, 'rt') as stream:
        for line in stream:
            item = json.loads(line)
            groups[item[key]].append(item['row'])
    return dict(groups)


def canonical_sha(obj):
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(text.encode()).hexdigest()


def near(a, b, label=''):
    assert np.allclose(a, b, rtol=0, atol=1e-12), (label, a, b)


def outcomes(row):
    valid = int(row['U'])
    rules = row['scores']['A']['rules']
    eligible = [x for x in rules if x is not None]
    style = Fraction(sum(eligible), len(eligible))
    return dict(US=float(valid * style), U=valid,
                hard3=valid * sum(rules[i] for i in [4, 5, 7]) / 3,
                all_rules=int(valid and all(eligible)))


def independent_interval(left, right, metric, unit):
    # Group full paired observations first, so stochastic samples and the three
    # method seeds cannot silently become independent confidence-interval units.
    per_unit = [defaultdict(list), defaultdict(list)]
    strata = {}
    field = 'id' if unit == 'prompt' else 'place'
    for idx, rows in enumerate([left, right]):
        for row in rows:
            key = row['prompt'][field]
            per_unit[idx][key].append(outcomes(row)[metric])
            value = row['prompt']['stratum']
            assert key not in strata or strata[key] == value
            strata[key] = value
    assert per_unit[0].keys() == per_unit[1].keys()
    differences = {key: sum(per_unit[0][key]) / len(per_unit[0][key])
                   - sum(per_unit[1][key]) / len(per_unit[1][key]) for key in strata}
    generator = np.random.default_rng(260928)
    replicates = np.zeros(10000)
    for stratum in sorted(set(strata.values())):
        keys = sorted(k for k in strata if strata[k] == stratum)
        vector = np.array([differences[k] for k in keys])
        indices = generator.integers(0, len(keys), (10000, len(keys)))
        replicates += np.sum(vector[indices], axis=1) / len(strata)
    return float(np.mean(list(differences.values()))), np.percentile(replicates, [2.5, 97.5])


def main():
    package = read('package.json')
    for name, expected in package['files'].items():
        assert hashlib.sha256((E / name).read_bytes()).hexdigest() == expected, name
    freeze = read('freeze.json')
    for name, expected in freeze['code_sha'].items():
        assert hashlib.sha256((E / 'frozen-code' / name).read_bytes()).hexdigest() == expected
    for name, expected in read('freeze-v1.json')['code_sha'].items():
        assert hashlib.sha256((E / 'frozen-code-v1' / name).read_bytes()).hexdigest() == expected
    prompts = read('prompts.json')
    assert canonical_sha(prompts) == freeze['prompts_sha']
    assert len(prompts) == 168 and len({p['id'] for p in prompts}) == 168
    prompt_map = {p['id']: p for p in prompts}
    tests = [p for p in prompts if p['split'] == 'heldout']
    assert Counter(p['stratum'] for p in tests) == {'familiar': 72, 'unseen': 72}
    assert set(Counter(p['place'] for p in tests).values()) == {6}
    assert len({p['place'] for p in tests}) == 24
    assert not {p['place'] for p in tests} & {p['place'] for p in prompts if p['split'] == 'dev'}
    assert all(p['sha256'] == hashlib.sha256(p['text'].encode()).hexdigest() for p in prompts)
    with gzip.open(E / 'reviews.jsonl.gz', 'rt') as stream:
        reviews = [json.loads(line) for line in stream]
    assert len(reviews) == 480 and canonical_sha(reviews) == freeze['archive_sha']
    review_map = {r['id']: r for r in reviews}
    usable = lambda rows: [r for r in rows if r['U'] and r['editor_valid']]
    assert [len(usable(reviews[:n])) for n in [15, 60, 480]] == [14, 55, 460]
    editor_diagnostic = read('editor-receipt-audit.json')
    assert editor_diagnostic['archive_sha256'] == freeze['archive_sha']
    assert editor_diagnostic['exact_pair_replays'] + len(editor_diagnostic['replay_mismatches']) == 460
    assert editor_diagnostic['exact_prompt_matches'] + len(editor_diagnostic['prompt_mismatches']) == editor_diagnostic['editor_prompt_receipts']

    def grams(premise):
        tokens = re.findall(r'\w+', premise.lower())
        return {tuple(tokens[i:i + 8]) for i in range(len(tokens) - 7)}
    old_prompts = read('old-prompts.json')
    grams_by_split = [set().union(*(grams(p['premise']) for p in group))
                      for group in [old_prompts, prompts[:24], tests]]
    assert all(not grams_by_split[a] & grams_by_split[b] for a, b in [(0, 1), (0, 2), (1, 2)])
    old_pairs = {tuple(sorted(p['anchors'])) for p in old_prompts}
    new_pairs = {tuple(sorted(p['anchors'])) for p in prompts}
    assert len(new_pairs) == len(prompts) and not old_pairs & new_pairs

    sys.path.insert(0, str(E / 'frozen-code/vendor'))
    sys.path.insert(0, str(E / 'frozen-code'))
    from compiler_validation import apply_deltas
    from run_experiment import apply_actions, parse_object, tool_actions
    from data import SYSTEM
    from style import RULES
    groups = load_groups('evaluations.jsonl.gz')
    books = read('playbooks.json')
    with gzip.open(E / 'provider-metadata.jsonl.gz', 'rt') as stream:
        receipts = {r['request']: r['receipt'] for line in stream for r in [json.loads(line)]}
    analysis = read('analysis.json')
    compact_plan = read('compact-rubric-plan.json')
    assert hashlib.sha256(compact_plan['prompt'].encode()).hexdigest() == compact_plan['prompt_sha256']
    for name, field in [('compact_rubric.py', 'script_sha256'), ('COMPACT_RUBRIC.md', 'protocol_sha256')]:
        assert hashlib.sha256((E / 'exploratory-code' / name).read_bytes()).hexdigest() == compact_plan[field]
    checked = 0
    raw_sums = {}
    for name, rows in groups.items():
        expected_n = 48 if name.startswith('dev-') else 288
        assert len(rows) == expected_n and len({r['id'] for r in rows}) == expected_n
        assert set(Counter(r['prompt']['id'] for r in rows).values()) == {2}
        raw_sums[name] = dict(episodes=len(rows), valid=sum(r['U'] for r in rows),
                             score_sum=sum(outcomes(r)['US'] for r in rows))
        for row in rows:
            assert row['prompt'] == prompt_map[row['prompt']['id']]
            if name in ['dev-base', 'test-base', 'test-explicit-rules', 'test-compact-rubric'] or '-raw-' in name or '-playbook-' in name:
                expected_policy = 'base'
            elif '-combined-' in name:
                expected_policy = name.removeprefix('test-').replace('combined-', 'sft-', 1)
            else:
                expected_policy = name.removeprefix('test-')
            assert row['policy'] == expected_policy, name
            sample = int(row['id'].rsplit('-', 1)[-1])
            assert sample in [0, 1]
            assert row['seed'] == 40000 + int(row['prompt']['id'].rsplit('-', 1)[-1]) * 31 + sample
            story, state, submitted = '', None, False
            messages = row['messages']
            assert len(messages) == 2 + 2 * row['turns'] and 1 <= row['turns'] <= 8
            assert messages[0]['role'] == 'system' and messages[1] == dict(role='user', content=(
                'Your assignment is also saved in prompt.md:\n' + row['prompt']['text'] + '\nWrite and submit story.md.'))
            system = messages[0]['content']
            if name.startswith('test-raw-'):
                budget = int(name.rsplit('-', 1)[1])
                prefix = SYSTEM + '\nPreviously reviewed examples:\n<examples>\n'
                suffix = '\n</examples>'
                assert system.startswith(prefix) and system.endswith(suffix)
                examples = [json.loads(line) for line in system[len(prefix):-len(suffix)].splitlines()]
                allowed = Counter(canonical_sha(dict(assignment=r['prompt']['text'], before=r['story'], after=r['edited']))
                                  for r in usable(reviews[:budget]))
                assert examples and all(set(x) == {'assignment', 'before', 'after'} for x in examples)
                assert Counter(map(canonical_sha, examples)) <= allowed
            elif '-playbook-' in name or '-combined-' in name or name in ['test-explicit-rules', 'test-compact-rubric']:
                if name == 'test-explicit-rules':
                    book_text = '\n'.join(f'{i+1}. {rule}' for i, rule in enumerate(RULES['A']))
                elif name == 'test-compact-rubric':
                    book_text = compact_plan['prompt']
                else:
                    match = re.search(r'-(?:playbook|combined)-(\d+)-s(\d+)$', name)
                    assert match, name
                    book_text = books[f'n{match[1]}-s{match[2]}']['playbook']
                assert system == SYSTEM + '\nInferred editorial playbook, learned from previous edits:\n' + book_text
            else:
                assert system == SYSTEM, name
            for index in range(2, len(messages), 2):
                assert messages[index]['role'] == 'assistant'
                turn = (index - 2) // 2
                receipt = receipts[row['id'] + f'-t{turn}']
                assert receipt['text'] == messages[index]['content']
                assert receipt['prompt_sha'] == canonical_sha(messages[:index])
                assert receipt['seed'] == row['seed'] + turn and receipt['policy'] == row['policy']
                assert receipt['model'] == 'Qwen/Qwen3-8B'
                assert receipt['params']['temperature'] == .7
                assert receipt['params']['max_tokens'] == 1800
                assert receipt['params']['top_p'] == .8 and receipt['params']['top_k'] == 20
                try:
                    actions = tool_actions(parse_object(messages[index]['content']))
                    story, state, submitted, outputs = apply_actions(actions, row['prompt'], story, state)
                except (ValueError, KeyError, TypeError, AttributeError):
                    outputs = [{'error': 'Return valid JSON: an object with an actions list of tool calls.'}]
                assert json.loads(messages[index + 1]['content']) == {'tool_results': outputs}, row['id']
                assert not submitted or index + 2 == len(messages)
            assert story == row['story'] and submitted == row['submitted'], row['id']
            assert submitted or row['turns'] == 8, row['id']
            count = len(story.split())
            anchors = {a: bool(re.search(r'\b' + re.escape(a) + r'\b', story, re.I)) for a in row['prompt']['anchors']}
            format_ok = 120 <= count <= 350 and all(anchors.values())
            assert row['format']['words'] == count and row['format']['required_words'] == anchors
            assert row['format']['pass'] == format_ok and row['U'] == (format_ok and submitted)
            scores = row['scores']['A']
            rules = scores['rules']
            assert rules[:4] == [not re.search(r'\bsuddenly\b', story, re.I),
                                 not re.search(r'\bvery\b', story, re.I), ';' not in story, '\u2014' not in story]
            assert rules[4] == (scores['present_share'] >= .9)
            assert rules[5] == (scores['first_words'] <= 12)
            assert rules[6] == (all(t.lower() == 'say' for t in scores['tag_verbs']) if scores['tag_verbs'] else None)
            assert rules[7] == (not scores['names'])
            near(scores['S'], sum(x for x in rules if x is not None) / sum(x is not None for x in rules))
            assert scores['words'] == count
            checked += 1
        for metric in ['US', 'U', 'hard3', 'all_rules']:
            near(np.mean([outcomes(r)[metric] for r in rows]), analysis['evaluations'][name][metric], name + metric)
        valid_rows = [r for r in rows if r['U']]
        if valid_rows:
            near(np.mean([r['scores']['A']['S'] for r in valid_rows]), analysis['evaluations'][name]['conditional_S'])
        else:
            assert analysis['evaluations'][name]['conditional_S'] is None

    intervals_checked = 0
    for n in [15, 60, 480]:
        arms = {m: sum([groups[f'test-{m}-{n}-s{s}'] for s in [31, 73, 127]], []) for m in ['sft', 'playbook']}
        for method, rows in arms.items():
            for metric in ['US', 'U', 'hard3', 'all_rules']:
                near(np.mean([outcomes(r)[metric] for r in rows]), analysis['methods'][f'{method}-{n}'][metric])
            valid = [r['scores']['A']['S'] for r in rows if r['U']]
            if valid:
                near(np.mean(valid), analysis['methods'][f'{method}-{n}']['conditional_S'])
            else:
                assert analysis['methods'][f'{method}-{n}']['conditional_S'] is None
            mean, interval = independent_interval(rows, groups['test-base'], 'US', 'prompt')
            near(mean, analysis['contrasts'][str(n)][method + '_minus_base']['mean'])
            near(interval, analysis['contrasts'][str(n)][method + '_minus_base']['ci95'])
            intervals_checked += 1
        for metric in ['US', 'U', 'hard3', 'all_rules']:
            for unit in ['prompt', 'place']:
                mean, interval = independent_interval(arms['sft'], arms['playbook'], metric, unit)
                reference = analysis['contrasts'][str(n)][metric][unit]
                near(mean, reference['mean'], f'{n} {metric} {unit}')
                near(interval, reference['ci95'], f'{n} {metric} {unit} interval')
                intervals_checked += 1
        near(np.mean([r['U'] for r in arms['sft']]) >= analysis['evaluations']['test-base']['U'] - .03,
             analysis['contrasts'][str(n)]['validity_guardrail'])

    sft = sum([groups[f'test-sft-480-s{s}'] for s in [31, 73, 127]], [])
    for method in ['combined', 'self', 'shuffled']:
        rows = sum([groups[f'test-{method}-480-s{s}'] for s in [31, 73, 127]], [])
        for metric in ['US', 'U', 'hard3', 'all_rules']:
            near(np.mean([outcomes(r)[metric] for r in rows]), analysis['followups'][method]['summary'][metric])
        valid = [r['scores']['A']['S'] for r in rows if r['U']]
        if valid:
            near(np.mean(valid), analysis['followups'][method]['summary']['conditional_S'])
        else:
            assert analysis['followups'][method]['summary']['conditional_S'] is None
        for metric, key in [('US', 'minus_sft'), ('U', 'validity_minus_sft')]:
            mean, interval = independent_interval(rows, sft, metric, 'prompt')
            near(mean, analysis['followups'][method][key]['mean'])
            near(interval, analysis['followups'][method][key]['ci95'])
            intervals_checked += 1

    training = read('training.json')
    targets = load_groups('training-targets.jsonl.gz', key='training')
    shuffle_maps = read('shuffle-maps.json')
    valid_ids = {r['id'] for r in usable(reviews)}
    for mapping in shuffle_maps.values():
        assert len(mapping) == 460
        assert {r['recipient'] for r in mapping} == {r['donor'] for r in mapping} == valid_ids
        for item in mapping:
            assert item['recipient'] != item['donor']
            recipient, donor = review_map[item['recipient']], review_map[item['donor']]
            replacements = dict(zip(donor['prompt']['anchors'], recipient['prompt']['anchors']))
            pattern = r'\b(?:' + '|'.join(map(re.escape, replacements)) + r')\b'
            remapped = re.sub(pattern, lambda m: replacements[m.group().lower()], donor['edited'], flags=re.I)
            assert remapped != recipient['edited']
            assert hashlib.sha256(remapped.encode()).hexdigest() == item['target_sha']
    for name, item in training.items():
        checkpoint = item['checkpoint']
        assert canonical_sha(targets[name]) == checkpoint['dataset_sha'], name
        assert len(targets[name]) == checkpoint['rows'] == len(item['masks'])
        assert [r['step'] for r in item['metrics']] == list(range(1, checkpoint['steps'] + 1))
        assert checkpoint['rank'] == checkpoint['batch'] == 16
        assert checkpoint['steps'] >= 30 and checkpoint['epochs'] >= 3
        assert checkpoint['loss_reduction'] == 'mean_per_example'
        selected = usable(reviews[:checkpoint['opportunities']])
        assert [r['id'] for r in targets[name]] == [r['id'] for r in selected]
        for target, mask in zip(targets[name], item['masks']):
            assert target['id'] == mask['id']
            assert mask['supervised_turns'] == 1 and 0 < mask['supervised_tokens'] < mask['tokens']
            assert target['messages'][-1]['role'] == 'assistant'
            assert target['target_turn'] == len(target['messages']) - 1
            assert target['prompt_id'].startswith('train-')
            source = review_map[target['id']]
            assert target['messages'][:-1] == source['messages'][:target['target_turn']], target['id']
            if checkpoint['target'] == 'shuffled':
                mapping = {r['recipient']: r for r in shuffle_maps[f'shuffle-s{checkpoint["seed"]}']}
                assert mapping[target['id']]['donor'] != target['id']
                expected_target_sha = mapping[target['id']]['target_sha']
            else:
                expected_target_sha = hashlib.sha256(source[checkpoint['target']].encode()).hexdigest()
            assert target['target_sha'] == expected_target_sha
            actions = tool_actions(parse_object(target['messages'][-1]['content']))
            final_write = [a for a in actions if a.get('tool') in ['write_file', 'edit_file']][-1]
            assert final_write['tool'] == 'write_file' and final_write['path'] == 'story.md'
            assert hashlib.sha256(final_write['content'].encode()).hexdigest() == expected_target_sha
        if not name.startswith('dev-'):
            assert checkpoint['learning_rate'] == freeze['learning_rate']
    archived = read('archive_manifest.json')['adapters']
    assert {r['name'] for r in archived} == set(training)
    assert all(r['bytes'] > 0 and r['sha256'] and r['members'] for r in archived)
    assert package['local_binary_archive_hashes_checked'] == len(archived)

    for book in books.values():
        selected = usable(reviews[:book['budget']])
        assert book['input_pair_sha'] == canonical_sha([(r['story'], r['edited']) for r in selected])
        assert book['valid_reviews'] == len(selected)
        assert len(book['history']) == (len(selected) + 14) // 15
        assert all(h['tokens'] <= 2000 for h in book['history'])
        assert all(set(op['evidence']) <= {r['id'] for r in selected[:15 * (h['batch'] + 1)]}
                   for h in book['history'] for op in h['operations'])
        rules, next_id = {}, 1
        for batch, history in enumerate(book['history']):
            assert history['batch'] == batch
            attempt = history.get('attempts', 1) - 1
            assert 0 <= attempt <= 2
            request = f'playbook-n{book["budget"]}-s{book["seed"]}-b{batch}'
            if attempt:
                request += f'-repair{attempt}'
            assert parse_object(receipts[request]['text'])['operations'] == history['operations']
            seen = {r['id'] for r in selected[:15 * (batch + 1)]}
            rules, next_id, text = apply_deltas(rules, next_id, history['operations'], seen)
            assert text == history['playbook']
        assert text == book['playbook']
        assert {str(k): v for k, v in rules.items()} == book['rules']
    compiler_inputs = 0
    with gzip.open(E / 'compiler-inputs.jsonl.gz', 'rt') as stream:
        for line in stream:
            row = json.loads(line)
            receipt = receipts[row['name']]
            assert receipt['prompt_sha'] == canonical_sha(row['messages']) and receipt['policy'] == 'editor'
            assert receipt['params']['temperature'] == .3 and receipt['params']['max_tokens'] == 4000
            payload = json.loads(row['messages'][1]['content'])
            assert set(payload) == {'current_rules', 'reviews'}
            for pair in payload['reviews']:
                assert set(pair) == {'id', 'assignment', 'before', 'after'}
                original = review_map[pair['id']]
                assert (pair['assignment'], pair['before'], pair['after']) == (
                    original['prompt']['text'], original['story'], original['edited'])
            compiler_inputs += 1

    retention = load_groups('retention.jsonl.gz')
    plan = read('retention-plan.json')
    official = read('official-ifeval/SOURCE.json')
    assert official['commit'] == 'e6890f85757dd84e27ca6df2dd30651dafad28e0'
    for name, record in official['files'].items():
        assert hashlib.sha256((E / 'official-ifeval' / name).read_bytes()).hexdigest() == record['sha256']
    official_rows = [json.loads(line) for line in
                     (E / 'official-ifeval/data/input_data.jsonl').read_text().splitlines()]
    selected = sorted(official_rows, key=lambda row: hashlib.sha256(
        ('retention-260928-' + str(row['key'])).encode()).hexdigest())[:128]
    assert selected == plan['rows']
    selected_by_key = {row['key']: row for row in selected}
    for name, rows in retention.items():
        assert len(rows) == 128 and {r['key'] for r in rows} == set(plan['keys'])
        for row in rows:
            assert {key: row[key] for key in selected_by_key[row['key']]} == selected_by_key[row['key']]
            strict = row['strict']
            receipt = receipts[f'ifeval-{name}-{row["key"]}']
            assert receipt['text'] == row['response'] and receipt['seed'] == 810000 + row['key']
            assert receipt['params']['max_tokens'] == 4096 and receipt['params']['temperature'] == .7
            system = plan['system']
            if name.startswith('playbook-'):
                seed = name.rsplit('-s', 1)[1]
                system += '\nPreviously learned writing preferences:\n' + books[f'n480-s{seed}']['playbook']
            prompt = [dict(role='system', content=system), dict(role='user', content=row['prompt'])]
            assert receipt['prompt_sha'] == canonical_sha(prompt)
            assert receipt['policy'] == ('base' if name == 'base' or name.startswith('playbook-') else name)
            assert strict['follow_all_instructions'] == all(strict['follow_instruction_list'])
            assert len(strict['follow_instruction_list']) == len(row['instruction_id_list'])
        near(np.mean([r['strict']['follow_all_instructions'] for r in rows]), analysis['retention'][name]['strict_prompt'])
        near(np.mean([v for r in rows for v in r['strict']['follow_instruction_list']]), analysis['retention'][name]['strict_instruction'])
    baseline = {r['key']: int(r['strict']['follow_all_instructions']) for r in retention['base']}
    for method in ['sft', 'playbook']:
        values = defaultdict(list)
        rows = sum([retention[f'{method}-480-s{s}'] for s in [31, 73, 127]], [])
        for row in rows:
            values[row['key']].append(int(row['strict']['follow_all_instructions']))
        vector = np.array([sum(values[k]) / 3 - baseline[k] for k in sorted(values)])
        generator = np.random.default_rng(260928)
        indices = generator.integers(0, 128, (10000, 128))
        interval = np.percentile(np.sum(vector[indices], axis=1) / 128, [2.5, 97.5])
        near(np.mean(vector), analysis['retention'][method + '-mean']['minus_base'])
        near(interval, analysis['retention'][method + '-mean']['ci95'])
        near(np.mean([r['strict']['follow_all_instructions'] for r in rows]),
             analysis['retention'][method + '-mean']['strict_prompt'])
        intervals_checked += 1

    costs = read('costs.json')
    charged = defaultdict(float)
    for record in costs:
        charged[record['request']] += record.get('estimated_usd', 0)
    rates = {'Qwen/Qwen3-8B': (.195, .60), 'thinkingmachines/Inkling': (1.87, 4.68)}
    for name, receipt in receipts.items():
        input_rate, output_rate = rates[receipt['model']]
        near(charged[name], (receipt['input_tokens'] * input_rate + receipt['output_tokens'] * output_rate) / 1e6)
    for name, item in training.items():
        near(charged[name], item['checkpoint']['training_tokens'] * .44 / 1e6)
    interrupted = read('interrupted-training.json')
    aborted_charges = {name.replace('-attempt', '-aborted-attempt'): item
                       for name, item in interrupted.items()}
    recognized = set(receipts) | set(training) | set(aborted_charges)
    assert all(record['request'] in recognized for record in costs if 'estimated_usd' in record)
    for request, item in aborted_charges.items():
        near(charged[request], item['started.json']['training_tokens'] * .44 / 1e6)
    near(sum(r.get('estimated_usd', 0) for r in costs), analysis['cost']['estimated_token_usd'])
    reserved = sum(r.get('reserved_usd', 0) for r in costs)
    near(reserved, analysis['cost']['reserved_usd'])
    assert reserved < 950
    for phase, count in [('style', 152), ('retention', 896)]:
        audit = read(f'rescore-{phase}.json')
        assert audit['status'] == 'passed' and not audit['mismatches'] and audit['checked'] == count
        for name, expected in audit['sources'].items():
            assert read('source-manifest.json')['runs/shared-reviews-20260928/' + name] == expected
    report = dict(status='passed', story_transcripts_replayed=checked,
                  summaries_recomputed=len(groups), paired_intervals_recomputed=intervals_checked,
                  retention_responses_checked=sum(map(len, retention.values())),
                  complete_training_runs=len(training), archived_adapters=len(archived),
                  interrupted_attempts_preserved=len(interrupted),
                  compiler_inputs_checked=compiler_inputs, shared_review_opportunities=len(reviews),
                  provider_receipts_linked=len(receipts),
                  linguistic_scores_rescored=152, official_retention_rescores=896,
                  older_archive_editor_replay_diagnostic=dict(
                      status=editor_diagnostic['status'],
                      exact_pair_replays=editor_diagnostic['exact_pair_replays'],
                      mismatching_pair_replays=len(editor_diagnostic['replay_mismatches']),
                      note='The new experiment shares the original saved pairs; this diagnostic did not fully reconstruct their earlier creation.'),
                  raw_counts=raw_sums, estimated_token_usd=analysis['cost']['estimated_token_usd'],
                  limits='Regex rules and linguistic-feature reductions checked; this is not human '
                         'validation of tense tagging, plot adherence, literary quality, or latent preferences.')
    (E / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Verified {checked} transcript replays, {intervals_checked} paired intervals, and {len(training)} training runs.')


if __name__ == '__main__':
    main()
