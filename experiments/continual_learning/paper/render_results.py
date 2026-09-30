"""Render paper figures and tables from the frozen analysis, without model calls."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
E = HERE / 'evidence'


def main(analysis_path=None, budget_only=False):
    data = json.loads((analysis_path or E / 'analysis.json').read_text())
    E.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 8,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'pdf.fonttype': 42, 'ps.fonttype': 42})
    fig, axes = plt.subplots(1, 2, figsize=(6.5, 2.05), sharex=True)
    colors = {'sft': '#315e9c', 'playbook': '#c0662e', 'raw': '#70757a'}
    budgets = [15, 60, 480]
    seeds = [31, 73, 127]
    for ax, metric, title in zip(axes, ['US', 'U'], ['Rubric score × validity', 'Valid submission']):
        for method, label, marker in [('sft', 'Corrected-target SFT', 'o'),
                                       ('playbook', 'Learned playbook', 's'),
                                       ('raw', 'Retrieved reviews', '^')]:
            means = []
            for x, n in enumerate(budgets):
                if method == 'raw':
                    values = [100 * data['evaluations'][f'test-raw-{n}'][metric]]
                else:
                    values = [100 * data['evaluations'][f'test-{method}-{n}-s{s}'][metric] for s in seeds]
                    ax.scatter(np.array([x] * 3) + [-.045, 0, .045], values,
                               s=11, color=colors[method], alpha=.4, zorder=3)
                means.append(float(np.mean(values)))
            ax.plot(range(3), means, color=colors[method], marker=marker,
                    markersize=4, linewidth=1.1, label=label, zorder=4)
        base = 100 * data['evaluations']['test-base'][metric]
        ax.axhline(base, color='#252525', linestyle=':', linewidth=1, label='No feedback')
        ax.set_title(title, fontsize=9, loc='left', pad=7)
        ax.set_xticks(range(3), [str(x) for x in budgets])
        ax.set_xlim(-.16, 2.16)
        if metric == 'US':
            ax.set_ylim(0, 102)
            ax.set_yticks([0, 25, 50, 75, 100])
        else:
            ax.set_ylim(80, 100.5)
            ax.set_yticks([80, 85, 90, 95, 100])
        ax.set_ylabel('Percent')
        ax.set_xlabel('Review opportunities')
        ax.grid(axis='y', color='#e1e4e8', linewidth=.5)
        ax.set_axisbelow(True)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=4, frameon=False,
               fontsize=7.4, bbox_to_anchor=(.5, -.035), handlelength=1.7, columnspacing=1.4)
    fig.tight_layout(rect=(0, .1, 1, 1), pad=.6, w_pad=1.8)
    fig.savefig(E / 'budget-comparison.pdf', bbox_inches='tight')
    fig.savefig(E / 'budget-comparison.png', dpi=220, bbox_inches='tight')
    plt.close(fig)
    points = {}
    for metric in ['US', 'U']:
        points[metric] = dict(base=data['evaluations']['test-base'][metric], methods={})
        for method in ['sft', 'playbook', 'raw']:
            points[metric]['methods'][method] = {}
            for n in budgets:
                keys = [f'test-raw-{n}'] if method == 'raw' else [f'test-{method}-{n}-s{s}' for s in seeds]
                values = [data['evaluations'][key][metric] for key in keys]
                points[metric]['methods'][method][str(n)] = dict(values=values, mean=float(np.mean(values)), policies=keys)
    (E / 'budget-visual-data.json').write_text(json.dumps(dict(
        points=points, budgets=budgets, method_seeds=seeds,
        axes=dict(US_percent=[0, 102], U_percent=[80, 100.5]),
        note='Categorical budget checkpoints; connecting lines guide the eye. '
             'Faint points are method seeds, not confidence bounds.'), indent=2) + '\n')
    if budget_only:
        print('Rendered the completed budget comparison.')
        return

    rows = [('No feedback', data['evaluations']['test-base']),
            ('Retrieved reviews', data['evaluations']['test-raw-480']),
            ('Learned playbook', data['methods']['playbook-480']),
            ('Corrected-target SFT', data['methods']['sft-480']),
            ('SFT + playbook', data['followups']['combined']['summary']),
            ('Unedited-target SFT', data['followups']['self']['summary']),
            ('Shuffled-target SFT', data['followups']['shuffled']['summary']),
            ('Verbatim rubric', data['evaluations']['test-explicit-rules']),
            ('Compact rubric', data['evaluations']['test-compact-rubric'])]
    lines = [r'\begin{tabular}{@{}lrrrr@{}}', r'\toprule',
             r'Method & $US$ & $U$ & $S\mid U$ & All rules \\', r'\midrule']
    for label, row in rows:
        if label == 'Verbatim rubric':
            lines.append(r'\midrule')
        vals = ['n/a' if row[k] is None else f'{row[k] * 100:.1f}'
                for k in ['US', 'U', 'conditional_S', 'all_rules']]
        lines.append(label + ' & ' + ' & '.join(vals) + r' \\')
    lines += [r'\bottomrule', r'\end{tabular}']
    (E / 'endpoint-table.tex').write_text('\n'.join(lines) + '\n')
    detail = dict(budgets=budgets,
                  endpoint_rows={label: {k: row[k] for k in ['US', 'U', 'conditional_S', 'all_rules']}
                                 for label, row in rows},
                  note='Figure shows method-seed points and arithmetic means; connecting lines '
                       'only guide the eye across three categorical budget checkpoints. No interpolated crossover.')
    (E / 'visual-data.json').write_text(json.dumps(detail, indent=2) + '\n')
    probe_rows = [('No adaptation', data['retention']['base']),
                  ('Active SFT adapter', data['retention']['sft-mean']),
                  ('Active playbook', data['retention']['playbook-mean'])]
    probe = [r'\begin{tabular}{@{}lrr@{}}', r'\toprule',
             r'Policy & Strict prompt & Strict instruction \\', r'\midrule']
    for label, row in probe_rows:
        probe.append(label + ' & ' + ' & '.join(f'{100 * row[k]:.1f}'
                     for k in ['strict_prompt', 'strict_instruction']) + r' \\')
    probe += [r'\bottomrule', r'\end{tabular}']
    (E / 'retention-table.tex').write_text('\n'.join(probe) + '\n')
    (E / 'retention-visual-data.json').write_text(json.dumps(
        {label: {k: row[k] for k in ['strict_prompt', 'strict_instruction']}
         for label, row in probe_rows}, indent=2) + '\n')
    print('Rendered the observed budget comparison and endpoint table.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--analysis', type=Path)
    parser.add_argument('--budget-only', action='store_true')
    args = parser.parse_args()
    main(args.analysis, args.budget_only)
