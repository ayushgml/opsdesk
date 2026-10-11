"""Provider access, usage accounting, and optional shared spend reservation."""
import contextlib
import fcntl
import json
import os
from pathlib import Path

PRICES = {
    "z-ai/glm-5.3": (0.039, 4.8),
    "qwen/qwen3.8-flash": (0.15, 0.47),
    "meta-llama/llama-3.1-8b-instruct": (0.05, 0.08),
    "google/gemini-3.8-flash": (0.75, 3.75),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-4-5-20250929": (3.0, 15.0),
}
MAX_OUTPUT_TOKENS = 1600


class Budget:
    """A locked ledger also works across independently launched eval processes."""
    def __init__(self):
        self.path = os.getenv("OPSDESK_BUDGET_FILE")
        self.limit = float(os.getenv("OPSDESK_BUDGET_USD", "4"))

    @contextlib.contextmanager
    def ledger(self):
        if not self.path:
            yield None
            return
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            file.seek(0)
            content = file.read()
            data = json.loads(content) if content else {"spent": 0.0, "reserved": 0.0, "calls": 0}
            try:
                yield data
            finally:
                file.seek(0)
                file.truncate()
                json.dump(data, file)
                file.flush()
                os.fsync(file.fileno())
                fcntl.flock(file, fcntl.LOCK_UN)

    def reserve(self, amount: float):
        with self.ledger() as data:
            if data is not None:
                if data.get("uncertain"):
                    raise RuntimeError("A prior request has unknown billing; reconcile budget before continuing")
                if data["spent"] + data["reserved"] + amount > self.limit:
                    raise RuntimeError("Calibration budget would be exceeded")
                data["reserved"] += amount

    def settle(self, amount: float, cost: float | None):
        with self.ledger() as data:
            if data is not None:
                data["reserved"] = max(0, data["reserved"] - amount)
                if cost is None:
                    data["uncertain"] = True
                else:
                    data["spent"] += cost
                data["calls"] += 1


class LLM:
    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER") or ("anthropic" if os.getenv("ANTHROPIC_API_KEY") else "openrouter")
        if self.provider not in {"anthropic", "openrouter"}:
            raise ValueError("LLM_PROVIDER must be anthropic or openrouter")
        self.model = os.getenv("VICTIM_MODEL") or ("claude-haiku-4-5-20251001" if self.provider == "anthropic" else "z-ai/glm-5.3")
        override = (os.getenv("VICTIM_PRICE_IN"), os.getenv("VICTIM_PRICE_OUT"))
        if any(value is not None for value in override) and not all(value is not None for value in override):
            raise ValueError("Set both VICTIM_PRICE_IN and VICTIM_PRICE_OUT")
        self.prices = tuple(map(float, override)) if all(value is not None for value in override) else PRICES.get(self.model)
        if self.prices is None or any(p < 0 for p in self.prices):
            raise ValueError("Unknown model pricing; set VICTIM_PRICE_IN and VICTIM_PRICE_OUT (USD/MTok)")
        self.tokens = {"input": 0, "output": 0}
        self.cost: float | None = 0.0
        self.budget = Budget()
        if self.provider == "anthropic":
            from anthropic import Anthropic
            if not os.getenv("ANTHROPIC_API_KEY"):
                raise ValueError("ANTHROPIC_API_KEY is not configured")
            self.client = Anthropic(max_retries=0, timeout=90)
        else:
            from openai import OpenAI
            if not os.getenv("OPENROUTER_API_KEY"):
                raise ValueError("OPENROUTER_API_KEY is not configured")
            self.client = OpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url="https://openrouter.ai/api/v1", max_retries=0, timeout=90)

    def complete(self, messages: list[dict], seed: int) -> str:
        # UTF-8 bytes bound ordinary tokenizer input; reserve extra framing overhead.
        input_bound = len(json.dumps(messages).encode()) + 2048
        reserve = (input_bound * self.prices[0] + MAX_OUTPUT_TOKENS * self.prices[1]) / 1_000_000
        self.budget.reserve(reserve)
        try:
            kwargs = {"model": self.model, "max_tokens": MAX_OUTPUT_TOKENS, "temperature": 0}
            if self.provider == "anthropic":
                kwargs.update(system=messages[0]["content"], messages=messages[1:])
                send = self.client.messages.create
            else:
                extra = {}
                if self.model.startswith("qwen/"):
                    extra["reasoning"] = {"enabled": False}
                elif self.model.startswith(("google/", "z-ai/")):
                    extra["reasoning"] = {"effort": "low"}
                kwargs.update(messages=messages, seed=seed, response_format={"type": "json_object"}, extra_body=extra)
                send = self.client.chat.completions.create
            try:
                response = send(**kwargs)
            except Exception as exc:
                if getattr(exc, "status_code", None) in {400, 422} and "temperature" in str(exc).lower():
                    kwargs.pop("temperature")
                    response = send(**kwargs)
                else:
                    raise
            if self.provider == "anthropic":
                usage = response.usage
                incoming, outgoing = usage.input_tokens, usage.output_tokens
                content = "".join(block.text for block in response.content if block.type == "text")
            else:
                usage = response.usage
                if usage is None:
                    raise RuntimeError("Provider returned no usage")
                incoming, outgoing = usage.prompt_tokens, usage.completion_tokens
                content = response.choices[0].message.content or ""
            self.tokens["input"] += incoming
            self.tokens["output"] += outgoing
            cost = (incoming * self.prices[0] + outgoing * self.prices[1]) / 1_000_000
            self.cost += cost
            self.budget.settle(reserve, cost)
            return content
        except Exception as exc:
            # Explicit HTTP rejections are unbilled. Network uncertainty must halt calibration.
            rejected = getattr(exc, "status_code", None) in {400, 401, 402, 403, 404, 422, 429}
            if not rejected:
                self.cost = None
            self.budget.settle(reserve, 0.0 if rejected else None)
            raise
