"""Entrypoints loaded by the credential-in-memory supervisor."""
from engine import MODEL, REVIEWER, get_engine, save


def dispatch(context, command):
    import importlib, engine as engine_module
    importlib.reload(engine_module)
    from engine import get_engine
    engine = get_engine(context)
    if command["op"] in {"pilot", "execute"}:
        for module_name in ("tasks", "lean_env", "protocol", "provers", "review", "scorer",
                            "train_cycle", "evaluate", "audit_history", "run_experiment"):
            importlib.reload(importlib.import_module(module_name))
    if command["op"] == "preflight":
        results = {}
        for model in (MODEL, REVIEWER):
            engine.setup(model)
            results[model] = engine.sample(
                "preflight/" + ("prover" if model == MODEL else "reviewer"),
                [{"role": "user", "content": "Reply with the JSON object {\"ready\":true} and nothing else."}],
                model=model, max_tokens=64, temperature=0)[0]["text"]
        save(engine.run / "provider-preflight.json", results)
        return {"event": "preflight_complete", "responses": results}
    if command["op"] == "pilot":
        import importlib, lean_env, provers, review, scorer, protocol
        importlib.reload(protocol)
        importlib.reload(lean_env)
        importlib.reload(provers)
        importlib.reload(review)
        importlib.reload(scorer)
        from concurrent.futures import ThreadPoolExecutor
        from tasks import catalogue
        from provers import ArmRepo, run_session
        from review import review_one
        from scorer import facts, score
        engine.setup(MODEL)
        engine.setup(REVIEWER)
        tasks = catalogue()["dev"]
        name = command.get("name", "pilot")
        arm = ArmRepo(engine.run, name, tasks)
        def one(i):
            record = run_session(engine, arm, f"{name}-t{i:02d}-s000", 0, i, forced=tasks[i].id)
            reviewed = review_one(engine, arm, record, prefix="pilot-reviews")
            truth = facts(record)
            return {"sid": record["sid"], "truth": sorted(truth),
                    "base": score(record["report"], truth, record["task"]["id"]),
                    "reviewed": None if reviewed.get("failed") else score(reviewed["corrected_report"], truth, record["task"]["id"])}
        with ThreadPoolExecutor(max_workers=10) as pool:
            result = list(pool.map(one, range(command.get("count", 10))))
        save(engine.run / "pilot-results.json", result)
        return {"event": "pilot_complete", "sessions": len(result), "results": result}
    if command["op"] == "execute":
        from run_experiment import execute
        return execute(engine)
    if command["op"] == "audit":
        from postprocess.export_adapters import export
        return export(engine)
    raise ValueError("Implementation is not ready for this phase")
