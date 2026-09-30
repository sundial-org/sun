"""Exploratory diagnostics from the completed, immutable evidence packet.

No inference or model selection. Length, tool use, and token counts help
interpret failures without equating planted-rule compliance with prose quality.
"""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
E = HERE / 'evidence'


def read_lines(name):
    with gzip.open(E / name, 'rt') as stream:
        return [json.loads(line) for line in stream]


def main():
    evaluations = read_lines('evaluations.jsonl.gz')
    receipts = {r['request']: r['receipt'] for r in read_lines('provider-metadata.jsonl.gz')}
    result = dict(status='exploratory descriptive analysis', policies={})
    for name in sorted({r['evaluation'] for r in evaluations}):
        rows = [r['row'] for r in evaluations if r['evaluation'] == name]
        counts = Counter()
        input_tokens = output_tokens = 0
        for row in rows:
            words = len(row['story'].split())
            counts['zero_words'] += words == 0
            counts['one_to_119_words'] += 0 < words < 120
            counts['120_to_129_words'] += 120 <= words < 130
            counts['over_350_words'] += words > 350
            counts['eight_turns'] += row['turns'] == 8
            counts['format_pass_without_submission'] += row['format']['pass'] and not row['submitted']
            counts['missing_anchor'] += not all(row['format']['required_words'].values())
            counts['valid'] += bool(row['U'])
            for turn in range(row['turns']):
                receipt = receipts[row['id'] + f'-t{turn}']
                input_tokens += receipt['input_tokens']
                output_tokens += receipt['output_tokens']
        invalid = sorted((r for r in rows if not r['U']),
                         key=lambda r: hashlib.sha256(('diagnostic-' + r['id']).encode()).hexdigest())
        result['policies'][name] = dict(
            episodes=len(rows), counts=dict(counts),
            word_quantiles=dict(zip(['min', 'p25', 'median', 'p75', 'max'],
                map(float, np.quantile([len(r['story'].split()) for r in rows], [0, .25, .5, .75, 1])))),
            assistant_turns=sum(r['turns'] for r in rows),
            sampling_input_tokens=input_tokens, sampling_output_tokens=output_tokens,
            token_estimate_usd=(input_tokens * .195 + output_tokens * .60) / 1e6,
            invalid_example_ids=[r['id'] for r in invalid[:3]],
        )
    result['notes'] = [
        'Counts overlap; they are diagnostic features, not exclusive causes.',
        'Input tokens include repeated multi-turn prefixes at uncached list price.',
        'Examples are selected by ID hash, not by perceived literary quality.',
        'No human plot, coherence, or literary-quality judgments are made.',
    ]
    (E / 'diagnostics.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f'Described {len(result["policies"])} completed evaluation policies.')


if __name__ == '__main__':
    main()
