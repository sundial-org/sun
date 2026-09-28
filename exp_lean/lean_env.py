"""Bounded Lean compiler wrapper. Receipts contain raw, immutable evidence."""
from __future__ import annotations
import hashlib
import difflib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

LEAN_ROOT = Path("/Users/bmo/.elan/toolchains/leanprover--lean4---v4.24.0")
LEAN = LEAN_ROOT / "bin/lean"
ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}


def run_lean(folder, filename, output=None, sandbox=True):
    folder = Path(folder).resolve()
    args = [str(LEAN), "-DmaxHeartbeats=200000", "-Dlinter.unusedSimpArgs=false",
            "-Dlinter.unusedVariables=false", "-T100000", filename]
    if output:
        args[1:1] = ["-o", output]
    if sandbox:
        profile = ('(version 1)(allow default)(deny network*)'
                   '(deny file-read-data (require-all (subpath "/Users/bmo")'
                   f'(require-not (subpath "{LEAN_ROOT}"))'
                   f'(require-not (subpath "{folder}"))))'
                   '(deny file-write* (require-all '
                   f'(require-not (subpath "{folder}"))'
                   '(require-not (literal "/dev/null"))))')
        args = ["/usr/bin/sandbox-exec", "-p", profile, *args]
    env = {"PATH": str(LEAN_ROOT / "bin") + ":/usr/bin:/bin", "LEAN_PATH": str(folder),
           "TMPDIR": str(folder), "LANG": "en_US.UTF-8"}
    start = time.monotonic()
    proc = subprocess.Popen(args, cwd=folder, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, start_new_session=True)
    timeout = False
    try:
        output_text = proc.communicate(timeout=30)[0]
    except subprocess.TimeoutExpired:
        timeout = True
        os.killpg(proc.pid, signal.SIGKILL)
        output_text = proc.communicate()[0]
    return {"output": output_text, "exit_code": proc.returncode,
            "timeout": timeout, "ms": int(1000 * (time.monotonic() - start)),
            "toolchain": "leanprover/lean4:v4.24.0", "file": filename}


def normalize_signature(text, lemma):
    # Strip comments before locating the target, with nested block-comment support.
    text = re.sub(r"--[^\n]*", "", text)
    old = None
    while old != text:
        old, text = text, re.sub(r"/\*(?:(?!/\*|\*/).)*\*/", "", text, flags=re.S)
    m = re.search(r"\btheorem\s+" + re.escape(lemma) + r"\s*:(.*?)\s*:=", text, re.S)
    return re.sub(r"\s+", "", m[1]) if m else None


def axioms(output, lemma):
    matches = re.findall(r"'" + re.escape(lemma) + r"' depends on axioms:\s*\[([^\]]*)\]", output)
    if matches:
        return [a.strip() for a in matches[-1].split(",") if a.strip()]
    if re.search(r"'" + re.escape(lemma) + r"' does not depend on any axioms", output):
        return []
    return None


def own_sorry_warning(source, output, lemma):
    match = re.search(r"\btheorem\s+" + re.escape(lemma) + r"\b", source)
    if not match:
        return False
    line = source[:match.start()].count("\n") + 1
    return bool(re.search(r"Attempt\.lean:" + str(line) + r":[0-9]+: warning: declaration uses ['\"]sorry['\"]", output))


def overwrote_proof(before, after, stub):
    norm = lambda line: re.sub(r"\s+", "", line.split("--", 1)[0])
    old, new = [norm(x) for x in before.splitlines()], [norm(x) for x in after.splitlines()]
    initial = {norm(x) for x in stub.splitlines()} | {""}
    return any(tag in {"replace", "delete"} and any(x not in initial for x in old[a:b])
               for tag, a, b, c, d in difflib.SequenceMatcher(None, old, new).get_opcodes())


def prepare(folder, task, prelude, dep_sources, dep_ids, reference=False):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Prelude.lean").write_text(prelude)
    receipt = run_lean(folder, "Prelude.lean", "Prelude.olean", sandbox=not reference)
    if receipt["exit_code"]:
        raise RuntimeError("Prelude did not compile: " + str(receipt["exit_code"]) + " " + receipt["output"][:2000])
    deps = "import Prelude\nopen Exp\n"
    for source in dep_sources:
        deps += re.sub(r"(?m)^import .*$", "", source) + "\n"
    (folder / "Deps.lean").write_text(deps)
    receipt = run_lean(folder, "Deps.lean", "Deps.olean", sandbox=not reference)
    if receipt["exit_code"]:
        raise RuntimeError("Dependencies did not compile: " + receipt["output"][:2000])
    (folder / "Expected.lean").write_text(
        f"import Deps\nopen Exp\ndef expected_{task.id} : Prop := {task.type}\n")
    receipt = run_lean(folder, "Expected.lean", "Expected.olean", sandbox=not reference)
    if receipt["exit_code"]:
        raise RuntimeError("Frozen statement did not compile: " + receipt["output"][:2000])
    return deps


def compile_attempt(folder, task, source, dep_ids, attempt, reference=False):
    folder = Path(folder)
    appended = "\n#print axioms " + task.id + "\n"
    appended += "".join(f"#print axioms {d}\n" for d in dep_ids)
    (folder / "Attempt.lean").write_text(source + appended)
    receipt = run_lean(folder, "Attempt.lean", "Attempt.olean", sandbox=not reference)
    receipt.update({"attempt": attempt, "source": source,
                    "source_sha256": hashlib.sha256(source.encode()).hexdigest()})
    receipt["axioms"] = axioms(receipt["output"], task.id)
    receipt["dependency_axioms"] = {d: axioms(receipt["output"], d) for d in dep_ids}
    receipt["recheck"] = None
    if receipt["exit_code"] == 0:
        (folder / "Recheck.lean").write_text(
            f"import Expected\nimport Attempt\nexample : expected_{task.id} := @{task.id}\n")
        receipt["recheck"] = run_lean(folder, "Recheck.lean", sandbox=not reference)
    return receipt
