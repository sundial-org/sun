"""Credential-in-memory supervisor for this experiment, with bounded commands."""
from __future__ import annotations

import argparse
import getpass
import importlib
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import sys
import traceback


def emit(value):
    print(json.dumps(value, default=str), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    run = Path(args.run).resolve()
    run.mkdir(parents=True, exist_ok=True)
    logging.disable(logging.CRITICAL)
    os.environ["TINKER_TELEMETRY"] = "0"
    os.environ.pop("TINKER_LOG", None)
    key = getpass.getpass("Tinker credential (memory only): ")
    if not key.startswith("tml-") or any(c.isspace() for c in key):
        raise SystemExit("Malformed credential")
    import tinker
    context = {"run": run, "key": key}
    try:
        service = tinker.ServiceClient(
            api_key=key, max_retries=0, timeout=60,
            base_url="https://tinker.thinkingmachines.dev/services/tinker-prod",
            user_metadata={"experiment": "ten-provers-lean", "run": run.name},
        )
        context["service"] = service
        capabilities = service.get_server_capabilities()
        models = [m.model_name for m in capabilities.supported_models]
        context["models"] = models
        emit({"event": "authenticated", "models": models,
              "versions": {k: importlib.metadata.version(k) for k in
                           ("tinker", "tinker-cookbook", "transformers")}})
    except Exception as exc:
        emit({"event": "setup_error", "type": type(exc).__name__,
              "message": str(exc).replace(key, "[REDACTED]")[:1600],
              "stack": [(Path(x.filename).name, x.lineno, x.name)
                        for x in traceback.extract_tb(exc.__traceback__)]})
    for line in sys.stdin:
        try:
            cmd = json.loads(line)
            if cmd["op"] == "stop":
                break
            if cmd["op"] not in {"preflight", "pilot", "execute", "audit"}:
                raise ValueError("Unsupported command")
            module = importlib.import_module("experiment")
            module = importlib.reload(module)
            emit(module.dispatch(context, cmd))
        except Exception as exc:
            emit({"event": "operation_error", "type": type(exc).__name__,
                  "message": str(exc).replace(key, "[REDACTED]")[:1600],
                  "stack": [(Path(x.filename).name, x.lineno, x.name)
                            for x in traceback.extract_tb(exc.__traceback__)]})


if __name__ == "__main__":
    main()
