"""Authoring helper: combine working sections into editable standalone LaTeX.

This is not called by build.py. Edit paper.tex directly after the final assembly.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent


def section(name):
    return '\n'.join(line for line in (HERE / name).read_text().splitlines()
                     if not line.lstrip().startswith('%')) + '\n'


def main():
    preamble = r'''\documentclass[10pt,twocolumn,letterpaper]{article}
\usepackage[pagenumbers]{cvpr}
\usepackage[T1]{fontenc}
\usepackage{microtype}
\usepackage[hidelinks]{hyperref}
\hypersetup{pdftitle={Learning a Writing Rubric from Edits: Context or Weights?}}
\raggedbottom
\hfuzz=0pt\vfuzz=0pt
\newcommand{\claim}[2]{#2}
\title{Learning a Writing Rubric from Edits: Context or Weights?}
\author{Research draft}
\begin{document}
\maketitle
'''
    workflow = r'''
\begin{figure*}[t]
\centering
\includegraphics[width=\textwidth]{evidence/workflow.pdf}
\caption{\claim{F01}{The two learned adaptation routes share public-valid review pairs. Private rubric labels are withheld from both learners; SFT also conditions on original trajectory prefixes. Each budget starts with a fresh playbook or adapter, and evaluation uses fresh assignments.}}
\label{fig:workflow}
\end{figure*}
'''
    budgets = r'''
\begin{figure*}[t]
\centering
\includegraphics[width=\textwidth]{evidence/budget-comparison.pdf}
\caption{\claim{F02}{Validity-adjusted rubric score and public validity across review budgets. Large markers show means; faint points show the three method seeds, not confidence bounds. The validity axis begins at 80\%. Budgets are categorical checkpoints and connecting lines only guide the eye.}}
\label{fig:budgets}
\end{figure*}
'''
    table = r'''
\begin{table}[t]
\centering\small
\setlength{\tabcolsep}{3pt}
\input{evidence/endpoint-table.tex}
\caption{\claim{T01}{Endpoint scores (percent). Playbook, SFT, and SFT-control rows pool three seeds; other rows use one policy. Each policy has 288 episodes. $S\mid U$ conditions on validity; all-rule success requires validity. The last two rows supply privileged rubric instructions, with the compact rendering added as an exploratory follow-up.}}
\label{tab:endpoint}
\end{table}
'''
    probe_table = r'''
\begin{table}[t]
\centering\small
\setlength{\tabcolsep}{4pt}
\input{evidence/retention-table.tex}
\caption{\claim{T02}{Active-policy instruction probe (percent). Every policy answers the same 128 IFEval prompts, containing 206 instruction checks, once. Adapter and playbook rows pool three seeds. Strict prompt accuracy requires all instructions in a prompt; instruction accuracy pools individual checks.}}
\label{tab:probe}
\end{table}
'''
    methods = section('methods-draft.tex')
    contribution = r'''\claim{C18}{Our central finding is a 17.4-point endpoint advantage for SFT in validity-adjusted rubric compliance. Lower-budget validity failures and training-seed variation qualify that gain, making task completion a separate part of the comparison rather than an assumed consequence of learning the rubric.}

'''
    methods = methods.replace(r'\section{Related work}', contribution + r'\section{Related work}')
    methods = methods.replace(r'\section{Experiments}', budgets + r'\section{Experiments}')
    text = (preamble + section('abstract-draft.tex') + workflow + methods
            + section('results-draft.tex') + table + probe_table + section('discussion-draft.tex')
            + section('references.tex') + '\\end{document}\n')
    (HERE / 'paper.tex').write_text(text)
    print('Assembled editable paper.tex from the current sections.')


if __name__ == '__main__':
    main()
