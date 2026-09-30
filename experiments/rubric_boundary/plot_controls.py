"""Plot both inference modes on the same 50-task subset."""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from run import ROOT,RUN,KINDS,SEEDS,read

def main():
    control=read(RUN/'control-analysis.json')
    rng=np.random.default_rng(93300)
    draws=np.concatenate([rng.choice(np.arange(i,50,5),size=(10000,10),replace=True) for i in range(5)],axis=1)
    values={}
    for kind in KINDS:
        values[kind]={}
        for label in ['base','trained']:
            fast=[];fast_tokens=[]
            for seed in SEEDS:
                policy='base' if label=='base' else f'sft-{kind}-{seed}'
                rows=read(RUN/'evaluations'/f'test-{policy}-{kind}-{seed}-retrieval.json')['rows'][:50]
                fast.append([r['exact'] for r in rows])
                fast_tokens += [read(RUN/'receipts'/f"{r['receipt']}.json")['output_tokens'] for r in rows]
            per_task=np.mean(fast,axis=0)
            lo,hi=np.quantile(per_task[draws].mean(axis=1),[.025,.975])
            reasoning=control['reasoning'][kind]
            values[kind][label]=dict(fast=dict(mean=float(per_task.mean()),low=float(lo),high=float(hi),tokens=float(np.mean(fast_tokens))),
                reasoning=dict(**reasoning[label],tokens=reasoning['base_tokens' if label=='base' else 'trained_tokens']))
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,3,figsize=(12,4),sharey=True)
    titles=['Clean corrections','Scattered errors','Regional blind spot']
    colors={'base':'#126C8A','trained':'#D56937'}
    for ax,kind,title in zip(axes,KINDS,titles):
        for label in ['base','trained']:
            pair=values[kind][label]
            x=[pair[m]['tokens'] for m in ['fast','reasoning']]
            y=[pair[m]['mean']*100 for m in ['fast','reasoning']]
            ax.plot(x,y,color=colors[label],alpha=.65,lw=1.5)
            for mode,marker in [('fast','o'),('reasoning','^')]:
                p=pair[mode]
                ax.errorbar(p['tokens'],p['mean']*100,yerr=np.array([[p['mean']-p['low']],[p['high']-p['mean']]])*100,
                    color=colors[label],marker=marker,markersize=7,capsize=3,ls='none')
        ax.set(title=title,xlabel='Mean output tokens (including reasoning)',ylim=(-2,104))
        ax.set_xlim(left=0)
        ax.grid(axis='y',alpha=.18)
    axes[0].set_ylabel('Completely correct tasks (%)')
    from matplotlib.lines import Line2D
    handles=[Line2D([0],[0],color=colors['base'],label='Context only'),Line2D([0],[0],color=colors['trained'],label='Context + weights'),
        Line2D([0],[0],color='#555555',marker='o',ls='none',label='Non-thinking'),Line2D([0],[0],color='#555555',marker='^',ls='none',label='Reasoning enabled')]
    fig.legend(handles=handles,loc='upper center',ncol=4,frameon=False,bbox_to_anchor=(.5,.92))
    fig.suptitle('Does enabling reasoning change the value of training?',fontsize=14,fontweight='bold',y=1)
    fig.text(.01,.01,'Same 50 tasks; strict output scoring. Intervals condition on seeds. Lines connect modes, not a fitted compute curve.',fontsize=8,color='#555555')
    fig.tight_layout(rect=(0,.04,1,.82))
    fig.savefig(ROOT/'controls.png',dpi=180)
    from run import write
    write(RUN/'control-visual-data.json',values)

if __name__=='__main__': main()
