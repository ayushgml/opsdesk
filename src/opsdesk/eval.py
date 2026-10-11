"""One task, one JSON result line, including failures."""
import argparse
import json
import os
from pathlib import Path
import time
import uuid

from .agent import run_agent
from .checks import evaluate
from .llm import LLM
from .runtime import Runtime


def redact(message: str) -> str:
    for name in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "NEATLOGS_API_KEY"):
        secret = os.getenv(name)
        if secret:
            message = message.replace(secret, "[redacted]")
    return message[:2000]


def load_task(task_id: str, directory: Path) -> dict:
    if not task_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in task_id):
        raise ValueError("Invalid task ID")
    candidates = [directory / f"{task_id}.json", directory / "heldout" / f"{task_id}.json"]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise ValueError(f"Unknown task: {task_id}")
    task = json.loads(path.read_text())
    if task["id"] != task_id:
        raise ValueError("Task ID does not match filename")
    return task


def run(task_id: str, seed: int, task_dir: Path | None = None, llm_factory=LLM) -> dict:
    start = time.monotonic()
    result = {"passed": False, "cost": 0.0, "latency": 0.0, "tokens": {"input": 0, "output": 0}, "trace_id": None, "error": None}
    llm = None
    trace = {"metadata": {k: os.environ[k] for k in ("CULPRIT_RUN_ID", "COMMIT_SHA", "TASK_ID", "REPETITION") if k in os.environ}, "task_id": task_id, "seed": seed}
    runtime = None
    try:
        task = load_task(task_id, task_dir or Path(os.getenv("OPSDESK_TASK_DIR", "evals")))
        runtime = Runtime(task["store"], task_id, seed, task.get("faults"))
        llm = llm_factory()
        trace["conversation"] = run_agent(task, runtime, llm, seed)
        failures = evaluate(task["checks"], runtime.store, runtime.log)
        result["passed"] = not failures
        result["error"] = "; ".join(failures) if failures else None
    except Exception as exc:
        result["error"] = redact(f"{type(exc).__name__}: {exc}")
    finally:
        if llm is not None:
            result["cost"], result["tokens"] = llm.cost, llm.tokens
        if runtime is not None:
            trace.update(store=runtime.store, tool_log=runtime.log)
        trace_id = str(uuid.uuid4())
        trace.update(result=result.copy(), trace_id=trace_id)
        try:
            directory = Path(os.getenv("OPSDESK_TRACE_DIR", ".opsdesk/traces"))
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{trace_id}.json").write_text(redact_trace(trace))
            result["trace_id"] = trace_id
        except OSError as exc:
            result["passed"] = False
            result["error"] = redact(f"Trace write failed: {exc}")
        result["latency"] = time.monotonic() - start
    return result


def redact_trace(trace: dict) -> str:
    output = json.dumps(trace, indent=2)
    for name in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "NEATLOGS_API_KEY"):
        if os.getenv(name):
            output = output.replace(os.environ[name], "[redacted]")
    return output + "\n"


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main():
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("--task", required=True)
        parser.add_argument("--seed", type=int, required=True)
        args = parser.parse_args()
        result = run(args.task, args.seed)
    except Exception as exc:
        result = {"passed": False, "cost": 0.0, "latency": 0.0, "tokens": {"input": 0, "output": 0}, "trace_id": None, "error": redact(str(exc))}
    print(json.dumps(result, separators=(",", ":"), allow_nan=False))


if __name__ == "__main__":
    main()
