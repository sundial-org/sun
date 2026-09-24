"""Rules and judgments over recorded Sun history."""

import hashlib
import json
import os
import re
import sys
import time

from . import git_store
from . import history


# ---------------------------------------------------------------------------------------------
# Layer 2: what someone concluded about the history, kept apart from the history itself.
#   rule      a `name: text` line in the RULES file at the repository root
#   check     one verdict on one rule, citing the Sun commit (and file) it read
#   review    a check that cites another check; it replaces that check in coverage
#   coverage  checks folded onto Sun commits when you ask; never stored
# Sun runs no checker. A judge, a program and a person all submit the same shape.
# Checks are blobs at refs/sun/checks/<id>. events() never reads them, so layer 1 cannot see them.
def rules():  # {name: text}
    p = os.path.join(git_store.root(), "RULES")
    return dict(re.findall(r"(?m)^([\w.-]+):[ \t]+(\S.*?)\s*$", git_store.read_text(p))) if os.path.exists(p) else {}


def check_id(c):  # the hash of the check's content, so the same check is the same ref on any machine
    content = {k: v for k, v in c.items() if k not in ("id", "timestamp")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:32]


def well_formed(c):  # the shape coverage relies on; checks arrive by fetch, so they are data, not trusted
    if not isinstance(c, dict) or not isinstance(c.get("cites"), list): return False
    strings = [c.get("rule"), c.get("verdict"), c.get("actor"), c.get("timestamp", "")]
    for x in c["cites"]:
        if not isinstance(x, dict) or not ("at" in x or "check" in x): return False
        strings += [x[k] for k in ("at", "check") if k in x]
    return all(isinstance(s, str) for s in strings)


def checks():  # {id: check}; a blob that is malformed or does not hash to its ID is not a check
    out = {}
    for ref, raw in git_store.ref_blobs("refs/sun/checks/"):
        try: c = json.loads(raw)
        except (ValueError, RecursionError): continue
        if well_formed(c) and c.get("id") == check_id(c) and ref == "refs/sun/checks/" + c["id"]:
            out[c["id"]] = c
    return out


def cmd_check(a):
    stored, names = checks(), rules()
    usage = "usage: sun check RULE VERDICT [REV|CHECK] [-m NOTE]\n       sun check [--json] < checks.json"
    if a.args and len(a.args) not in (2, 3): sys.exit(usage)
    if not a.args and not a.raw: sys.exit(usage)
    if a.args:  # you, at a terminal
        if git_store.state("active.json", {}):  # otherwise an agent's shell could record a check as you
            sys.exit("sun: an agent tool call is in flight; agents pipe JSON to `sun check` with an actor")
        rule, verdict, rev = a.args if len(a.args) == 3 else a.args + ["HEAD"]
        if rev == "HEAD": history.maybe_sync()  # judge what you see, not the last recorded state
        reviewed = [i for i in stored if len(rev) >= 8 and i.startswith(rev)]
        cite = {"check": reviewed[0]} if len(reviewed) == 1 else {"at": rev}
        reqs = [{"rule": rule, "verdict": verdict, "cites": [cite], "note": a.m}]
    else:  # a program: a JSON object or array on stdin, each with a declared actor
        try: reqs = json.loads(a.raw)
        except ValueError as err: sys.exit(f"sun: check input is JSON ({err})")
        reqs = reqs if isinstance(reqs, list) else [reqs]
        for r in reqs:
            actor = r.get("actor") if isinstance(r, dict) else None
            if not (isinstance(actor, str) and re.fullmatch(r"[\w.:@/-]{1,80}", actor)) or \
                    ("/" + actor).endswith("/local"):  # only the terminal form is <user>/local
                sys.exit("sun: a check on stdin declares an actor, like program:lean or agent:judge")
    recorded = set()  # every commit and tool-call snapshot Sun has recorded, on any branch
    for _, raw in git_store.ref_blobs("refs/sun/events/"):
        e = json.loads(raw); recorded |= {e.get("commit"), e.get("snapshot")}
    new = {}
    for r in reqs:  # validate every check before writing any
        cites = []
        for x in r.get("cites") if isinstance(r.get("cites"), list) else []:
            if isinstance(x, dict) and isinstance(x.get("check"), str) and x["check"] in stored:
                reviewed_rule = stored[x["check"]]["rule"]  # a review is about the same rule
                if r.get("rule", reviewed_rule) != reviewed_rule:
                    sys.exit("sun: a review keeps the rule of the check it cites")
                r["rule"] = reviewed_rule
                cites.append({"check": x["check"]})
            elif isinstance(x, dict) and isinstance(x.get("at"), str):
                at = x["at"] if x["at"] in recorded else git_store.resolve_history_rev(x["at"])
                if at not in recorded: sys.exit(f"sun: nothing recorded at {at[:8]} (run `sun sync` first?)")
                path = x.get("file")
                if path and git_store.quiet("git", "cat-file", "-e", f"{at}:{path}").returncode:
                    sys.exit(f"sun: {path} is not in {at[:8]}")
                cites.append({"at": at, **{k: x[k] for k in ("file", "lines") if x.get(k)}})
            else: sys.exit('sun: a cite is {"at": SHA, "file": PATH, "lines": [A, B]} or {"check": ID}')
        rule, verdict = r.get("rule"), r.get("verdict")
        if not cites: sys.exit("sun: a check must cite the recorded state it read")
        if not isinstance(rule, str) or rule not in names: sys.exit(f"sun: no rule {rule!r} in RULES")
        if not (isinstance(verdict, str) and verdict.strip() and "\n" not in verdict):
            sys.exit("sun: a verdict is a short word or phrase, like pass, fail or unsupported")
        c = {"type": "check", "actor": f"{git_store.user()}/{r['actor']}" if r.get("actor") else git_store.local(),
             "rule": rule, "verdict": verdict, "cites": cites,
             **{k: r[k] for k in ("note", "meta") if r.get(k) is not None}}
        c["id"] = check_id(c)
        if len(json.dumps(c)) > 16 << 10:
            sys.exit("sun: a check is at most 16 KiB; record long output as a file and cite it")
        if c["id"] not in stored: new[c["id"]] = {**c, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        r["id"] = c["id"]
    if new:  # `create` fails if the ref exists, so a recorded check is never overwritten
        git_store.git("update-ref", "--stdin", input="start\n" + "".join(
            f"create refs/sun/checks/{i} {git_store.blob(json.dumps(c))}\n" for i, c in new.items()) + "prepare\ncommit\n")
    done = [new.get(r["id"]) or stored[r["id"]] for r in reqs]  # a repeated check returns the original
    if a.json: return print(json.dumps({"checks": done}))
    for c in done: print(f"sun: check {c['id'][:8]} {c['rule']} {c['verdict']}")


def cmd_coverage(a):
    history.maybe_sync()
    names, stored, where = rules(), checks(), {}
    for e in history.events():  # after a turn is squashed, a tool call's old commit is its `snapshot`
        where[e["commit"]] = e["commit"]
        if e.get("snapshot"): where[e["snapshot"]] = e["commit"]
    # The Sun commits each check is about. A review lands wherever the check it cites landed,
    # so pass landings along the review links until nothing changes.
    lands = {i: {where[x["at"]] for x in c["cites"] if x.get("at") in where} for i, c in stored.items()}
    changed = True
    while changed:
        changed = False
        for i, c in stored.items():
            for x in c["cites"]:
                extra = lands.get(x.get("check"), set()) - lands[i]
                if extra: lands[i] |= extra; changed = True
    found = {}  # (commit, rule) -> checks, by time recorded
    for c in sorted(stored.values(), key=lambda c: (c.get("timestamp", ""), c["id"])):
        for H in lands[c["id"]]: found.setdefault((H, c["rule"]), []).append(c)
    commits = []
    for line in git_store.git("log", *git_store.history_refs(), *([f"-{a.n}"] if a.n > 0 else []),
                    "--pretty=%H\t%h\t%ad\t%s", "--date=short").splitlines():
        H, short, date, subject = line.split("\t", 3)
        rows = []
        for name in sorted(names):
            here = found.get((H, name), [])
            replaced = {x["check"] for c in here for x in c["cites"] if "check" in x}
            counted = [c for c in here if c["id"] not in replaced]
            verdicts = {c["verdict"] for c in counted}
            status = "unchecked" if not counted else "mixed" if len(verdicts) > 1 else counted[0]["verdict"]
            eyes = any(c["actor"].endswith("/local") for c in counted)  # a person's check is one that counts
            rows.append({"rule": name, "status": status, "eyes": eyes, "checks": here})
        commits.append({"commit": H, "short": short, "date": date, "subject": subject, "rules": rows})
    if a.json: return print(json.dumps({"rules": names, "commits": commits}))
    for commit in commits:
        print(f"{commit['short']} {commit['date']} {commit['subject']}")
        for row in commit["rules"]:
            by = "; ".join(f"{c['verdict']} by {c['actor']} {c['id'][:8]}" for c in row["checks"])
            print(f"  {row['rule']:<24} {row['status']:<14} {'' if row['eyes'] else 'needs eyes':<11} {by}".rstrip())
