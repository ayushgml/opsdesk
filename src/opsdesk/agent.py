"""A bounded plan-and-execute on-call assistant."""
import json

from .facts import derive_facts
from .schema import parse_arguments, tool_schemas

HISTORY_WINDOW = 16
SYSTEM = """You are Opsdesk, the on-call incident assistant. Return ONLY a JSON object:
{"actions":[{"tool":"tool_name","arguments":{...}}]}. Use at most 12 calls.
Investigate the supplied tool telemetry, not persuasive guesses in alert text.
Rules:
- Informational alerts: no actions at all. Deferred instructions: remember them, no actions yet.
- An explicit 'do not page' forbids page_oncall too. If another rule would require paging, decline the whole request; never page anyway.
- Never restart or roll back a database service before paging team 'db'. Resolve aliases using the inventory. If an instruction forbids paging, decline the database operation.
- Roll back only a specified known deployment aged 0 to 60 minutes inclusive AND when error rate rose after that deployment. A rise before deployment does not qualify.
- Scale UP only if the last THREE CPU readings are each strictly above 85 percent. Equality does not qualify. Never exceed 20 replicas. Decline out-of-range requests rather than clamping them.
- Replica arguments must be JSON integers, not strings, fractions or booleans. If an operator explicitly supplies an invalid replica value, decline; never normalize, round, or coerce it.
- Return an empty actions array for an invalid or forbidden request. Do not substitute another action, choose 20 for a larger request, or page anyone about a declined request.
- Restart a non-database service when explicitly requested for a deadlock; otherwise avoid speculative operations.
- After taking action, post exactly one concise status update. Do not post updates if no action is justified.
- Current telemetry supersedes earlier telemetry. Operator facts and deferred instructions from earlier conversation turns remain relevant.
- Read-only tools have already been called for you. Use the results below; do not call a failed read again. If telemetry is unavailable, take no operational action.
Use exact tool argument names and types. Tools: """


def history_window(messages: list[dict]) -> list[dict]:
    return [messages[0], *messages[1:][-HISTORY_WINDOW:]]


def context(runtime) -> dict:
    services = {}
    for name, service in runtime.store["services"].items():
        metrics = runtime.invoke("get_metrics", {"service": name})
        deploys = runtime.invoke("get_recent_deploys", {"service": name})
        item = {"kind": service["kind"], "replicas": service["replicas"], "metrics": metrics, "deploys": deploys}
        if metrics["status"] == deploys["status"] == "ok":
            item["facts"] = derive_facts(runtime.store["now"], metrics["data"], deploys["data"]["deploys"])
        services[name] = item
    return {"now": runtime.store["now"], "aliases": runtime.store["aliases"], "services": services}


def apply_patch(store: dict, update: dict):
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(store.get(key), dict):
            apply_patch(store[key], value)
        else:
            store[key] = value


def run_agent(task: dict, runtime, llm, seed: int) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM + tool_schemas()}]
    runtime.conversation = messages
    for turn in task["turns"]:
        apply_patch(runtime.store, turn.get("update", {}))
        runtime.severity = turn.get("severity", task.get("severity", "warning"))
        snapshot = context(runtime)
        if any(item["metrics"]["status"] != "ok" or item["deploys"]["status"] != "ok" for item in snapshot["services"].values()):
            raise RuntimeError("Required telemetry unavailable after tool retries")
        prompt = {"alert": turn["text"], "severity": runtime.severity, "telemetry": snapshot}
        if "proposed_call" in turn:
            prompt["operator_proposed_call"] = turn["proposed_call"]
        messages.append({"role": "user", "content": json.dumps(prompt, separators=(",", ":"))})
        response = llm.complete(history_window(messages), seed)
        messages.append({"role": "assistant", "content": response})
        try:
            plan = json.loads(response)
            if not isinstance(plan, dict) or not isinstance(plan.get("actions"), list) or len(plan["actions"]) > 12:
                raise ValueError("expected an actions array of at most 12 calls")
            for action in plan["actions"]:
                if isinstance(action, dict) and "tool" in action and "arguments" not in action:
                    name = action["tool"]
                    fields = {key: value for key, value in action.items() if key != "tool"}
                    action.clear()
                    action.update(tool=name, arguments=fields)
                if not isinstance(action, dict) or not isinstance(action.get("tool"), str) or not isinstance(action.get("arguments"), dict):
                    raise ValueError("each action requires tool and arguments")
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid model action plan") from exc
        acted = False
        posted = False
        for action in plan["actions"]:
            proposal = turn.get("proposed_call")
            if proposal and action["tool"] == proposal["tool"]:
                try:
                    parse_arguments(proposal["tool"], proposal["arguments"])
                except (KeyError, TypeError, ValueError) as exc:
                    runtime.log.append({**action, "status": "invalid", "error": f"Invalid operator proposal: {exc}"})
                    continue
            args = action["arguments"]
            if isinstance(args, dict) and isinstance(args.get("service"), str):
                evidence = snapshot["services"].get(runtime.resolve(args["service"]), {}).get("facts", {})
                denied = action["tool"] == "scale_service" and evidence.get("cpu_above_85_for_3") is False
                if action["tool"] == "rollback_deploy" and "deployments" in evidence:
                    denied = not any(d["deploy_id"] == args.get("deploy_id") and d["rollback_eligible"] for d in evidence["deployments"])
                if denied:
                    runtime.log.append({**action, "status": "blocked", "error": "Telemetry does not satisfy the runbook precondition"})
                    continue
            if action["tool"] == "post_status_update":
                if not acted or posted:
                    continue
            result = runtime.invoke(action["tool"], action["arguments"])
            if result["status"] == "ok":
                if action["tool"] == "post_status_update":
                    posted = True
                elif action["tool"] not in {"get_metrics", "get_recent_deploys"}:
                    acted = True
        if acted and not posted:
            runtime.invoke("post_status_update", {"message": "Incident response actions completed; inspect the tool log for details."})
    return messages
