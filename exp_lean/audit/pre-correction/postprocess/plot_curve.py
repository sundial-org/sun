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
    rows = json.load(source)["curve"]
plt.rcParams.update({"font.size": 8, "font.family": "DejaVu Serif",
                    "pdf.fonttype": 42, "axes.spines.top": False,
                    "axes.spines.right": False})
fig, ax = plt.subplots(figsize=(4.0, 1.95), layout="constrained")
for key, label, color, marker in [("base", "Base", "#777777", None),
                                ("context", "Context", "#1c5790", "o"),
                                ("weights", "Weights", "#bc5f12", "s")]:
    ax.plot([r["reviews"] for r in rows], [r[key] for r in rows],
            color=color, label=label, marker=marker, markersize=3.5,
            linewidth=1.4, linestyle="--" if key == "base" else "-")
ax.set(xlim=(-8, 488), ylim=(0, 1.025), xlabel="Cumulative reviews", ylabel="Mean F")
ax.set_xticks([0, 120, 240, 360, 480])
ax.set_yticks([0, .25, .5, .75, 1])
ax.grid(axis="y", color="#dddddd", linewidth=.5)
ax.set_axisbelow(True)
ax.legend(loc="lower center", bbox_to_anchor=(.5, 1.01), ncol=3,
          frameon=False, fontsize=7.5, borderaxespad=0)
fig.savefig(sys.argv[2])
