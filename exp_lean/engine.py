"""Provider calls, replayable receipts, and conservative token accounting."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import threading
import time
import types

MODEL = "Qwen/Qwen3-8B"
REVIEWER = "deepseek-ai/DeepSeek-V3.1"
RATES = {MODEL: {"prefill": .195, "sample": .60, "train": .44},
         REVIEWER: {"prefill": 1.695, "sample": 4.215, "train": 3.718}}
PRICING_SOURCE = "https://tinker-docs.thinkingmachines.ai/tinker/models/"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256((value if isinstance(value, str) else canonical(value)).encode()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, indent=2, ensure_ascii=False)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(raw + "\n")
    temp.replace(path)


class Engine:
    def __init__(self, context):
        self.context, self.run = context, Path(context["run"])
        self.service = context["service"]
        self.lock = threading.Lock()
        self.tokenizer_lock = threading.RLock()
        self.renderers, self.tokenizers, self.clients = {}, {}, {}
        self.reserved = 0.0
        ledger = self.run / "cost-reservations.jsonl"
        if ledger.exists():
            self.reserved = sum(json.loads(x)["ceiling_usd"] for x in ledger.read_text().splitlines())
        self.install_transport_retries()

    def install_transport_retries(self):
        # Retry the same SDK operation and sequence ID, not a new sample call.
        # Model responses are never retried or selected according to their content.
        import asyncio
        import tinker
        async def bounded(_holder, func, *args, **kwargs):
            for attempt in range(4):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    status = getattr(exc, "status_code", None)
                    transient = isinstance(exc, tinker.APIConnectionError) or (status is not None and 500 <= status < 600)
                    if not transient or attempt == 3:
                        raise
                    self.log("transport_retry", operation=getattr(func, "__name__", "sdk_operation"),
                             attempt=attempt + 1, error_type=type(exc).__name__, status=status)
                    await asyncio.sleep(2 ** attempt)
        self.service.holder.execute_with_retries = types.MethodType(bounded, self.service.holder)

    def log(self, event, **data):
        item = {"event": event, "time": time.time(), **data}
        with self.lock:
            with (self.run / "events.jsonl").open("a") as f:
                f.write(canonical(item) + "\n")
        print(canonical(item), flush=True)

    def setup(self, model):
        from tinker_cookbook.tokenizer_utils import get_tokenizer
        from tinker_cookbook.renderers import get_renderer
        from tinker.lib.retry_handler import RetryConfig
        if model not in self.renderers:
            self.log("loading_model", model=model)
            tokenizer = get_tokenizer(model)
            name = "qwen3_disable_thinking" if model == MODEL else "deepseekv3"
            self.tokenizers[model] = tokenizer
            self.renderers[model] = get_renderer(name, tokenizer)
            self.clients[model] = self.service.create_sampling_client(
                base_model=model, retry_config=RetryConfig(enable_retry_logic=False,
                                                        progress_timeout=600))
            self.log("model_ready", model=model, renderer=name)

    def reserve(self, identity, model, prompt=0, output=0, train=0):
        rate = RATES[model]
        amount = (prompt * rate["prefill"] + output * rate["sample"] + train * rate["train"]) / 1e6
        with self.lock:
            if self.reserved + amount > 450:
                raise RuntimeError("Experiment reached its USD 450 reservation ceiling")
            self.reserved += amount
            with (self.run / "cost-reservations.jsonl").open("a") as f:
                f.write(canonical({"id": identity, "model": model, "prompt_tokens": prompt,
                                   "max_output_tokens": output, "training_tokens": train,
                                   "ceiling_usd": amount, "time": time.time()}) + "\n")

    def sample(self, identity, messages, model=MODEL, client=None, policy="base",
               max_tokens=1024, temperature=.7, seed=31, n=1):
        import tinker
        receipt_path = self.run / "samples" / (identity + ".json")
        prompt_hash = digest(messages)
        if receipt_path.exists():
            cached = json.loads(receipt_path.read_text())
            assert cached["prompt_hash"] == prompt_hash and cached["policy"] == policy
            return cached["outputs"]
        renderer = self.renderers[model]
        supplied_messages = list(messages)
        with self.tokenizer_lock:
            prompt = renderer.build_generation_prompt(supplied_messages)
            stops = renderer.get_stop_sequences()
            # Preserve the initial evidence and the newest complete tool turns.
            # This applies equally to every reviewer/analyst, never to provers.
            while model == REVIEWER and prompt.length + max_tokens > 32000 and len(supplied_messages) > 4:
                supplied_messages = supplied_messages[:2] + supplied_messages[4:]
                prompt = renderer.build_generation_prompt(supplied_messages)
        if len(supplied_messages) != len(messages):
            self.log("review_context_trimmed", identity=identity,
                     original_messages=len(messages), retained_messages=len(supplied_messages))
        if prompt.length + max_tokens > 32000:
            raise RuntimeError(f"Sequence too long: {identity} {prompt.length}")
        pending = self.run / "submissions" / (identity + ".json")
        raw_path = self.run / "provider-outputs" / (identity + ".json")
        if pending.exists() and not raw_path.exists():
            raise RuntimeError(f"Ambiguous previous submission: {identity}")
        start = time.monotonic()
        if raw_path.exists():
            sequences = json.loads(raw_path.read_text())
        else:
            self.reserve(identity, model, prompt.length * n, max_tokens * n)
            save(pending, {"identity": identity, "prompt_hash": prompt_hash,
                           "policy": policy, "submitted_at": time.time()})
            response = (client or self.clients[model]).sample(
                prompt=prompt, num_samples=n,
                sampling_params=tinker.types.SamplingParams(
                    max_tokens=max_tokens, temperature=temperature, seed=seed,
                    stop=stops)).result(timeout=900)
            sequences = [{"tokens": s.tokens, "logprobs": s.logprobs, "stop_reason": s.stop_reason,
                          "sequence_id": getattr(s, "sequence_id", None)} for s in response.sequences]
            save(raw_path, sequences)
        outputs = []
        for sequence in sequences:
            with self.tokenizer_lock:
                message, parsed = renderer.parse_response(sequence["tokens"])
            content = message.get("content", "")
            text = content if isinstance(content, str) else "".join(
                x.get("text", "") for x in content if x.get("type") == "text")
            outputs.append({"text": text, **sequence, "parsed": bool(parsed)})
        save(receipt_path, {"identity": identity, "model": model, "policy": policy,
                            "prompt_hash": prompt_hash, "messages": messages,
                            "supplied_messages": supplied_messages,
                            "prompt_tokens": prompt.length, "max_output_tokens": max_tokens,
                            "temperature": temperature, "seed": seed,
                            "seconds": time.monotonic() - start, "outputs": outputs})
        return outputs


def get_engine(context):
    if "engine" not in context:
        context["engine"] = Engine(context)
    else:
        context["engine"].__class__ = Engine
        if not hasattr(context["engine"], "tokenizer_lock"):
            context["engine"].tokenizer_lock = threading.RLock()
        context["engine"].install_transport_retries()
    return context["engine"]
