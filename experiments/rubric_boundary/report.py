"""Generate a concise research report and a separate evidence ledger."""
import hashlib
import json
from run import ROOT,RUN,read,write

def pct(x): return f'{100*x:.1f}%'
def pp(x): return f'{100*x:+.1f}'
def effect(x): return f"{pp(x['mean'])} [{100*x['low']:.1f}, {100*x['high']:.1f}]"

def main():
    a=read(RUN/'analysis.json')
    c=read(RUN/'control-analysis.json')
    diagnostics={d['name']:d for d in read(RUN/'diagnostics.json')}
    selected=a['selection']['selected']
    rows={r['kind']:r for r in a['comparisons'] if r['style']==selected}
    names={'clean':'Clean (100% correct)','scattered':'Scattered errors (80% correct)','systematic':'Regional blind spot (80% correct)'}
    ledger={}
    def claim(key,text,justification,sources,data=None):
        ledger[key]=dict(text=text,justification=justification,sources=sources)
        if data is not None: ledger[key]['verified_values']=data
        return text+f' [{key}]'
    lines=['# Learning a Rubric from Imperfect Corrections','',
        '## Research question','',
        'When the complete correct rubric stays in context, does the pattern of equally frequent correction errors change the benefit of updating weights?', '',
        claim('M1','The experiment compares clean corrections with two archives that are each 80% correct: scattered mistakes and a consistent west-region blind spot. Every mistake ignores the recall override on one order.',
              'Check all nine correction pools against both exact oracles. Noisy pools each have 80 incorrect whole examples out of 400; the other orders retain their correct decisions.',
              ['runs/20260929-policy-v2/pools/','task.py','test_task.py']), '',
        '## Method','',
        claim('M2','Nine Qwen3-8B LoRA adapters use 400 shared training inputs, three epochs, and three seeds per correction condition. Evaluation uses 250 held-out three-order tasks. Frozen and trained models receive the same complete rules, checklist, and four retrieved examples.',
              'The frozen protocol, training manifests, complete 75-step logs, saved supervised examples, and evaluation receipts establish these settings. Retrieval was selected on 50 development tasks from 0, 4, 8, and 16 example alternatives.',
              ['PROTOCOL.md','runs/20260929-policy-v2/freeze.json','runs/20260929-policy-v2/training/','runs/20260929-policy-v2/selection.json']), '',
        claim('M4','All 95% intervals resample test tasks within region while holding the three training seeds fixed. They do not estimate uncertainty over new training runs.',
              'The primary and reasoning analyses average the three seeds within each task before the stratified bootstrap. The paired region control resamples its 50 west-origin pairs. Per-seed values are retained to expose between-run variation.',
              ['analyze.py','controls.py: analyze','results.json: comparisons[].seeds']), '',
        '## Results','',
        '| Correction source | Context only | Context + weights | Paired gain, percentage points [95% interval] |',
        '|---|---:|---:|---:|']
    for i,(kind,r) in enumerate(rows.items(),1):
        v=r['metrics']['exact']
        text=f"| {names[kind]} | {pct(v['base']['mean'])} | {pct(v['trained']['mean'])} | {effect(v['delta'])} |"
        marked=claim(f'R{i}',text,'Completely correct output, averaged over method seeds within each task. Paired 10,000-draw task bootstrap stratified by focus region; intervals condition on the three seeds. All raw responses were rescored.',[f'results.json: comparisons[{kind}, {selected}].metrics.exact','analyze.py'])
        lines.append(marked.replace(f'| [R{i}]',f'[R{i}] |'))
    lines += ['', '![Complete-task success and recall handling](results.png)', '',
        claim('R4',f"The difference between the training gains under scattered and systematic errors is {effect(a['noise_interaction'])} percentage points. The prespecified practical-reversal criterion was {'met' if a['practical_reversal'] else 'not met'}.",
              'Difference-in-differences is paired by task. The reversal rule requires one gain interval entirely above +3 points and the other entirely below -3 points. A source difference without opposite signs is not a strategy reversal.',
              ['results.json: noise_interaction, practical_reversal','PROTOCOL.md']), '',
        '| Correction source | All decisions correct, context | All decisions correct, trained |', '|---|---:|---:|']
    for kind,r in rows.items():
        m=r['metrics']['decisions_exact']
        lines.append(f"| {names[kind]} | {pct(m['base']['mean'])} | {pct(m['trained']['mean'])} |")
    lines += ['',claim('R5','The decision-only measure ignores output ordering while retaining exact IDs, allocations, and routes; the primary measure additionally requires the requested order.',
                    'The scorer independently compares the per-ID dictionaries and the ordered output. Table values are the decisions_exact fields of the same verified responses.',
                    ['task.py: score','results.json: comparisons[].metrics.decisions_exact'],
                    {k:r['metrics']['decisions_exact'] for k,r in rows.items()}), '',
        '| Adding retrieved examples to the complete rules | Effect on frozen model | Effect on trained model |',
        '|---|---:|---:|']
    for kind,r in a['context_example_effects'].items():
        lines.append(f"| {names[kind]} | {effect(r['base'])} | {effect(r['trained'])} |")
    lines += ['',claim('R8','The example-context effects compare the same models with four retrieved examples versus the complete policy/checklist alone, in percentage points of complete-task success.',
                    'The diagnostic was included in the frozen protocol. Effects are paired within the same 250 tasks; both sides retain the full correct policy. These are additional contrasts rather than the primary noise-interaction test.',
                    ['results.json: context_example_effects','analyze.py'],a['context_example_effects']), '']
    blindspot=[diagnostics[f'test-sft-systematic-{s}-systematic-{s}-retrieval']['regions']['west'] for s in [31,73,127]]
    totals={k:sum(r[k] for r in blindspot) for k in blindspot[0]}
    baseline=next(r for r in rows['systematic']['regions'] if r['region']=='west')['base']['recall_correct']
    lines += [claim('R9',f"The regional-error adapters correctly handle {totals['correct_recall']} of {totals['n']} west recall evaluations ({pct(totals['correct_recall']/totals['n'])}), versus {pct(baseline)} for the frozen model. Of the failures, {totals['valid_recall_violations']} are valid complete responses with the wrong recall decision and {totals['schema_failures']} are invalid responses. These are the same 50 tasks evaluated across three adapters, not 150 independent tasks.",
                    'Sum the west-region diagnostic counts across the three systematic adapters. The correct action is HOLD with zero units. Separating valid rule violations from malformed output shows that the collapse is not simply a JSON-format effect. This subgroup outcome was specified before test collection.',
                    ['runs/20260929-policy-v2/diagnostics.json','results.json: systematic regions'],dict(totals=totals,per_seed=blindspot,base_recall=baseline)), '',
        '## Additional controls','',
        claim('M3','The following controls were specified after the frozen baseline was observed and before any trained test result was inspected. They do not replace the primary endpoint.',
                    'The original control freeze is dated 19:28:08 UTC, before the first trained model completed at 19:28:24 UTC. An operational amendment increased concurrency before collecting any control responses; it changed no scientific settings.',
                    ['runs/20260929-policy-v2/control-original/control-freeze.json','runs/20260929-policy-v2/control-freeze.json','runs/20260929-policy-v2/main.log']), '',
        '| Correction source | Reasoning context only | Reasoning + weights | Paired gain on 50 tasks [95% interval] |', '|---|---:|---:|---:|']
    for kind,r in c['reasoning'].items():
        lines.append(f"| {names[kind]} | {pct(r['base']['mean'])} | {pct(r['trained']['mean'])} | {effect(r['delta'])} |")
    clean_reasoning=c['reasoning']['clean']
    assert clean_reasoning['nonthinking_delta_same_tasks']['low']>0 and clean_reasoning['delta']['high']<0
    reasoning_errors={}
    for kind in rows:
        ds=[diagnostics[f'reasoning-sft-{kind}-{s}-{kind}-{s}'] for s in [31,73,127]]
        reasoning_errors[kind]=dict(n=sum(d['n'] for d in ds),
            counts={k:sum(d['counts'][k] for d in ds) for k in ds[0]['counts']})
    norm=', '.join(f"{kind}: {pct(d['counts']['normalized_exact']/d['n'])}" for kind,d in reasoning_errors.items())
    clean_errors=reasoning_errors['clean']['counts']
    lines += ['',claim('R6','The reasoning control gives both policies a 4,096-token output allowance and uses the same 50 tasks and retrieved examples within each paired comparison.',
                    'CONTROL_PROTOCOL and control-freeze precede trained test inspection. The separately cached Qwen3 thinking receipts and control analysis establish settings, exact success, and intervals.',
                    ['CONTROL_PROTOCOL.md','runs/20260929-policy-v2/control-freeze.json','runs/20260929-policy-v2/control-analysis.json: reasoning'],c['reasoning']), '',
        claim('R10',f"With clean corrections on those same 50 tasks, the training gain is {effect(clean_reasoning['nonthinking_delta_same_tasks'])} points in non-thinking mode and {effect(clean_reasoning['delta'])} points with reasoning enabled. Mean output length in reasoning mode is {clean_reasoning['base_tokens']:.0f} tokens for the frozen model and {clean_reasoning['trained_tokens']:.0f} for the trained models. This secondary comparison identifies a mode-dependent reversal, not an equal-cost threshold.",
                    'Use only the common 50-task subset for both mode-specific differences. The independently scored reasoning control stores the corresponding non-thinking difference. Output length counts every sampled token, including reasoning. The same maximum allowance is not the same realized token consumption.',
                    ['runs/20260929-policy-v2/control-analysis.json: reasoning.clean','runs/20260929-policy-v2/control-visual-data.json'],clean_reasoning), '',
        claim('R11',f"A post hoc wrapper check changes trained reasoning-mode success to {norm}. It removes only a whole code fence or a lone unclosed `<think>` tag followed entirely by JSON. The clean result is unchanged: among its {150-clean_errors['exact_correct']} failures across three runs, {clean_errors['sorting_only_failures']} have correct decisions in the wrong order, {clean_errors['schema_failures']} have invalid outputs, and {clean_errors['valid_decision_failures']} have valid outputs with wrong decisions.",
                    'diagnostics.py scores both the untouched final response and a strictly delimited wrapper-normalized response. It never searches prose for a favorable JSON object. The clean error partition is disjoint and asserted to sum to all evaluated outputs. This robustness analysis was added after inspecting control responses and is not a replacement endpoint.',
                    ['diagnostics.py','runs/20260929-policy-v2/diagnostics.json'],reasoning_errors), '',
        '![Inference effort and task success](controls.png)', '',
        '| Model | Recall success, original west | Same order moved to north | Paired change [95% interval] |','|---|---:|---:|---:|']
    for kind,r in c['counterfactual'].items():
        lines.append(f"| {'Frozen model' if kind=='base' else names[kind]} | {pct(r['west']['mean'])} | {pct(r['north']['mean'])} | {effect(r['north_minus_west'])} |")
    cf_seeds=[dict(seed=s,**diagnostics[f'region-sft-systematic-{s}']['regions']['north']) for s in [31,73,127]]
    cf_rates=', '.join(f"seed {d['seed']}: {pct(d['correct_recall']/d['n'])}" for d in cf_seeds)
    lines += ['',claim('R7','The region control changes only the recalled order’s region; its correct answer stays identical. It uses the complete policy and checklist without retrieved examples.',
                    'control-inputs stores all 50 pairs; both oracle implementations assert unchanged gold answers. Raw originals are reused from the main checklist condition and counterfactual responses are independently rescored.',
                    ['controls.py','runs/20260929-policy-v2/control-inputs.json','runs/20260929-policy-v2/control-analysis.json: counterfactual'],c['counterfactual']), '',
        claim('R12',f"For the regional-error adapters, north-region recall success varies sharply by run ({cf_rates}). Seed 73 produces 50 malformed responses; its zero score cannot be interpreted as 50 valid wrong recall decisions. The other two adapters recover correct recall handling on 49 of 50 pairs each.",
                    'Read the per-region diagnostic partition for the three region-sft-systematic control groups. Every original west checklist recall score is zero. The per-seed numbers qualify the average and its task-only interval; format failure prevents a clean semantic interpretation for seed 73.',
                    ['runs/20260929-policy-v2/diagnostics.json','runs/20260929-policy-v2/controls/region-sft-systematic-73.json'],cf_seeds), '',
        '## Interpretation and next vector','',
        claim('I1','The primary test did not find opposite preferred strategies for the two equally accurate correction sources. It did find improved overall execution alongside a learned regional rule failure. The secondary reasoning control challenges the premise that this task needs weight updates: the frozen model already reaches 98% with clean examples on its 50 tasks.',
                    'The two primary noisy-source gain intervals are positive. R9 verifies valid recalled-order action errors in the systematic subgroup. R6 verifies the frozen clean reasoning baseline; its smaller test set and different mode are stated explicitly. This interpretation is restricted to the observed model, task, and recipe.',
                    ['results.json','runs/20260929-policy-v2/control-analysis.json','runs/20260929-policy-v2/diagnostics.json']), '',
        '**Proposed next vector:** Does the mode reversal survive training that explicitly preserves reasoning? Hold the 400 clean inputs and three seeds fixed, compare final-answer training with training on verified reasoning traces, and measure accuracy against actual inference-token use. If the reversal disappears, the present boundary mainly reflects the training recipe. If it persists, mapping the accuracy/compute tradeoff becomes the priority. A broader feedback-reliability threshold is premature.', '',
        '## Scope and limitations','',
        claim('L1','This study tests one synthetic task family, one fixed policy, one model, one training-data size, and one nonzero error rate. It does not locate a general data threshold, test generated rubrics, or establish cross-domain transfer.',
                    'The complete protocol grid has no other task family, dynamic policy, data-size condition, or error-rate condition.', ['PROTOCOL.md','INTERPRETATION_LIMITS.md']), '',
        claim('L2','The noisy archives match accuracy and corruption operation, but not the distribution of incorrect route labels. Consequently, any difference cannot be attributed solely to error predictability.',
                    'For seed 31, the scattered corrupted targets contain 40 EXPRESS and 40 STANDARD decisions; systematic corrupted targets contain 80 STANDARD decisions. West-region shipping explains this difference.',
                    ['INTERPRETATION_LIMITS.md','runs/20260929-policy-v2/pools/scattered-31.json','runs/20260929-policy-v2/pools/systematic-31.json']), '',
        claim('L3','Fine-tuning supervises final answers in non-thinking mode. It does not teach reasoning traces or explicitly preserve reasoning behavior. The reasoning result therefore applies to this training recipe; it does not establish that fine-tuning generally harms reasoning.',
                    'Training exports contain the correct policy, task, and final JSON target, rendered with qwen3_disable_thinking. The supervised-token checks confirm that only the final answer and termination are targets. There is no reasoning-preservation training arm.',
                    ['run.py: Study.train','runs/20260929-policy-v2/training/','INTERPRETATION_LIMITS.md']), '',
        claim('L4','The rule system has an ordinary executable solution. Recall-success measurements require a valid complete response, so malformed outputs count as failures.',
                    'Both deterministic oracle implementations compute the complete answer from the input records. The scorer builds its per-ID prediction dictionary only after validating the entire response schema and ID set.',
                    ['task.py: oracle, independent_oracle, score']), '',
        '## Verification and cost','',
        claim('V1',f"The analysis replays {a['unique_test_responses']:,} unique primary test responses and checks frozen source/data hashes, both task oracles, all completed training steps, and the additional control responses. Estimated token charges for this cycle, including development and controls, are ${a['cost']['estimated_usd']:.2f}; estimated cumulative charges including the earlier writing study are ${a['cost']['total_estimated_usd']:.2f}.",
                    'analysis.json verification records primary replay and training checks; controls.analyze replays its raw receipts. Cost sums the current and initial-development ledgers, including conservative interrupted-attempt charges, then adds the prior study estimate. Estimates exclude storage and invoice adjustments.',
                    ['runs/20260929-policy-v2/analysis.json','runs/20260929-policy-v2/control-analysis.json','runs/20260929-policy-v2/costs.jsonl','runs/20260929/costs.jsonl']), '',
        'The previous writing paper and its frozen evidence remain unchanged. See [protocol](PROTOCOL.md), [nearest neighbors](NEIGHBORS.md), [interpretation limits](INTERPRETATION_LIMITS.md), and [claim justifications](CLAIMS.md).','']
    report='\n'.join(lines)
    (ROOT/'REPORT.md').write_text(report)
    claim_lines=['# Claim justifications','', 'These are evidence explanations, not merely artifact hashes. Intervals are conditional on the observed training seeds.','']
    for key,v in ledger.items():
        claim_lines += [f'## {key}', '',v['text'],'',v['justification'],'','Sources: '+', '.join(f'`{p}`' for p in v['sources']), '']
    (ROOT/'CLAIMS.md').write_text('\n'.join(claim_lines))
    evidence_paths=[ROOT/'results.json',RUN/'control-analysis.json',RUN/'diagnostics.json',RUN/'control-visual-data.json',RUN/'freeze.json',RUN/'control-freeze.json']
    write(ROOT/'claim-checks.json',dict(report_sha256=hashlib.sha256(report.encode()).hexdigest(),claims=ledger,
        evidence_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in evidence_paths},
        analysis_code_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/n for n in ['report.py','analyze.py','diagnostics.py','plot_controls.py']]}))

if __name__=='__main__': main()
