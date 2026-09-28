"""Keep the supplied Tinker credential in memory throughout this experiment."""
import getpass
import importlib
import json
import logging
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
BASE_URL = "https://tinker.thinkingmachines.dev/services/tinker-prod"


def main():
    import httpx
    logging.disable(logging.CRITICAL)
    os.environ["TINKER_TELEMETRY"] = "0"
    key = getpass.getpass("Tinker credential (memory only): ")
    with httpx.Client(base_url=BASE_URL, headers={"X-API-Key": key},
                      timeout=30, follow_redirects=False) as client:
        response = client.get(BASE_URL + "/api/v1/get_server_capabilities")
        print(json.dumps({"event": "capabilities", "status": response.status_code,
                          "data": response.json() if response.is_success else None}), flush=True)
    print(json.dumps({"event": "ready"}), flush=True)
    for line in sys.stdin:
        command = json.loads(line)
        if command["op"] == "stop":
            break
        try:
            module = importlib.import_module("run_experiment")
            module = importlib.reload(module)
            module.execute(command, key)
        except Exception as error:
            print(json.dumps({"event": "failed", "error_type": type(error).__name__,
                              "status": getattr(error, "status_code", None),
                              "attribute": getattr(error, "name", None)}), flush=True)


if __name__ == "__main__":
    main()
