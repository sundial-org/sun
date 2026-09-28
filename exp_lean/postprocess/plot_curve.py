"""Vector plot for the one-page LaTeX report."""
import json
import sys
import os
from pathlib import Path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / ".cache" / "report-packages"))
os.environ.setdefault("MPLCONFIGDIR", str(root / ".cache" / "matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

with open(sys.argv[1]) as source:
    analysis = json.load(source)
rows = analysis["curve"]
with open(sys.argv[3]) as source:
    audit = json.load(source)
plt.rcParams.update({"font.size": 8, "font.family": "DejaVu Serif",
                    "pdf.fonttype": 42, "axes.spines.top": False,
                    "axes.spines.right": False})
fig, ax = plt.subplots(figsize=(4.0, 2.2), layout="constrained")
for key, label, color, marker in [("context", "Context", "#1c5790", "o"),
                                ("weights", "Weights", "#bc5f12", "s")]:
    # Only draw segments between observed trained/reviewed checkpoints.
    # The zero-review point is one shared, independently sampled baseline.
    ax.plot([r["reviews"] for r in rows[1:]], [r[key] for r in rows[1:]],
            color=color, label=label, marker=marker, markersize=3.5,
            linewidth=1.4)
ax.axhline(rows[0]["base"], color="#777777", linestyle="--", linewidth=1,
           label="Base (measured once)")
ax.plot([0], [rows[0]["base"]], marker="D", markersize=4, color="#777777")
ax.axhline(audit["always_E4_F"], color="#6d5486", linestyle=":", linewidth=1.3,
           label="Always E4 (0.942)")
ax.text(.98, .49, "113/120 failure traces; 0 proved/partial\nWeights match a post hoc exit-code rule",
        ha="right", va="center", transform=ax.transAxes, fontsize=7,
        color="#444444", linespacing=1.5)
ax.set(xlim=(-8, 488), ylim=(0, 1.045), xlabel="Reviews in shared pool", ylabel=r"Mean header score ($P\times R$)")
ax.set_xticks([0, 120, 240, 360, 480])
ax.set_yticks([0, .25, .5, .75, 1])
ax.grid(axis="y", color="#dddddd", linewidth=.5)
ax.set_axisbelow(True)
ax.legend(loc="lower center", bbox_to_anchor=(.5, 1.01), ncol=2,
          frameon=False, fontsize=7, borderaxespad=0)
fig.savefig(sys.argv[2])
