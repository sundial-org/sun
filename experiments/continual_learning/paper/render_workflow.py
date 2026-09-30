"""Draw the study design as a vector figure, without experimental results."""
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = Path(__file__).resolve().parent


def main():
    out = HERE / 'evidence'
    out.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 8,
                         'pdf.fonttype': 42, 'ps.fonttype': 42})
    fig, ax = plt.subplots(figsize=(6.5, 1.48))
    ax.set(xlim=(0, 10), ylim=(0, 2.1))
    ax.axis('off')
    ink, blue, orange = '#202b37', '#315e9c', '#b65b27'

    def box(x, y, w, h, title, detail, edge=ink, fill='#f3f5f7'):
        ax.add_patch(FancyBboxPatch((x, y), w, h,
                     boxstyle='round,pad=0.035,rounding_size=0.055',
                     linewidth=.8, edgecolor=edge, facecolor=fill))
        ax.text(x+w/2, y+h*.69, title, ha='center', va='center',
                weight='bold', fontsize=8.2, color=edge)
        ax.text(x+w/2, y+h*.30, detail, ha='center', va='center',
                fontsize=7.2, color=ink, linespacing=1.2)

    def arrow(start, end, color=ink):
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle='-|>',
                     mutation_scale=9, linewidth=.9, color=color,
                     shrinkA=3, shrinkB=4))

    box(.06, .57, 2.22, .94, 'Shared review pairs',
        'Assignment\nDraft + revision')
    ax.text(1.17, 1.82, 'Edits encode a private rubric',
            ha='center', va='center', color=ink, fontsize=7.4)
    ax.text(1.17, .26, '14 / 55 / 460 usable pairs',
            ha='center', va='center', color=ink, fontsize=7.3)
    box(3.04, 1.17, 2.16, .75, 'Context', 'Inferred playbook',
        edge=orange, fill='#fcf0e8')
    box(3.04, .12, 2.16, .75, 'Weights', 'Corrected-turn LoRA',
        edge=blue, fill='#eaf0f8')
    arrow((2.3, 1.20), (3.0, 1.54), orange)
    arrow((2.3, .88), (3.0, .49), blue)
    ax.text(4.12, 1.02, 'SFT also uses trajectory prefixes',
            ha='center', va='center', fontsize=6.6, color=ink)
    box(5.98, .62, 1.53, .86, 'Writer', 'Fresh assignments')
    arrow((5.23, 1.54), (5.95, 1.20), orange)
    arrow((5.23, .49), (5.95, .89), blue)
    box(8.20, .62, 1.72, .86, 'Evaluation', 'Rubric score\n× public validity')
    arrow((7.54, 1.05), (8.16, 1.05))
    ax.text(7.97, 1.82, '144 prompts · 2 samples per policy',
            ha='center', va='center', fontsize=7.4, color=ink)
    ax.text(7.97, .26, 'Three construction / training seeds',
            ha='center', va='center', fontsize=7.3, color=ink)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    fig.savefig(out / 'workflow.pdf', bbox_inches='tight', pad_inches=.015)
    fig.savefig(out / 'workflow.png', dpi=240, bbox_inches='tight', pad_inches=.015)
    plt.close(fig)
    print('Rendered the shared-review workflow diagram.')


if __name__ == '__main__':
    main()
