"""Deterministic local tools with transactional result validation."""
import copy
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, StrictFloat, StrictInt, StrictStr, TypeAdapter
from typing import Literal

from .policy import check_policy
from .schema import parse_arguments

MAX_RETRIES = 3


class Result(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    status: Literal["ok"]
    data: dict


class Reading(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    at: StrictStr
    value: StrictFloat | StrictInt


class Metrics(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    cpu: list[Reading]
    errors: list[Reading]


class Deploy(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    id: StrictStr
    at: StrictStr


def validate_result(name: str, payload: dict) -> dict:
    result = Result.model_validate(payload).model_dump()
    data = result["data"]
    if name == "get_metrics":
        Metrics.model_validate(data)
    elif name == "get_recent_deploys":
        if set(data) != {"deploys"}:
            raise ValueError("missing deployments")
        TypeAdapter(list[Deploy]).validate_python(data["deploys"], strict=True)
    elif data != {"applied": True} or type(data["applied"]) is not bool:
        raise ValueError("mutation result must acknowledge application")
    return result


class Runtime:
    def __init__(self, store: dict, task_id: str, seed: int, faults: list[dict] | None = None):
        self.store = copy.deepcopy(store)
        self.store.setdefault("pages", [])
        self.store.setdefault("updates", [])
        self.store.setdefault("aliases", {})
        self.log: list[dict] = []
        self.task_id, self.seed = task_id, seed
        self.faults = copy.deepcopy(faults or [])
        self.counts: dict[str, int] = {}
        self.severity = "warning"

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.store, indent=2) + "\n")

    def resolve(self, service: str) -> str:
        return self.store["aliases"].get(service, service)

    def fault(self, name: str, args: dict) -> str | None:
        key = name + ":" + args.get("service", "")
        index = self.counts.get(key, 0)
        self.counts[key] = index + 1
        for rule in self.faults:
            if rule["tool"] != name or rule.get("service", args.get("service")) != args.get("service"):
                continue
            sequence = rule.get("sequence")
            if sequence is None:
                digest = hashlib.sha256(f"{self.task_id}:{self.seed}:{key}".encode()).digest()
                choices = ["timeout", "failed", "malformed"]
                sequence = [choices[digest[i] % len(choices)] for i in range(rule.get("failures", 0))]
            if index < len(sequence):
                return sequence[index]
        return None

    def invoke(self, name: str, arguments: dict) -> dict:
        entry = {"tool": name, "arguments": copy.deepcopy(arguments)}
        try:
            args = parse_arguments(name, arguments)
            if "service" in args:
                args["service"] = self.resolve(args["service"])
                if args["service"] not in self.store["services"]:
                    raise ValueError("unknown service")
        except (ValueError, KeyError, TypeError) as exc:
            self.log.append({**entry, "status": "invalid", "error": str(exc)})
            return {"status": "invalid", "error": str(exc)}
        blocked = None
        if blocked:
            self.log.append({**entry, "status": "blocked", "error": blocked})
            return {"status": "blocked", "error": blocked}
        for attempt in range(MAX_RETRIES + 1):
            try:
                fault = self.fault(name, args)
                if fault == "timeout":
                    raise TimeoutError("mock tool timeout")
                candidate = copy.deepcopy(self.store)
                payload = self.execute(candidate, name, args)
                if fault == "failed":
                    payload = {"status": "failed"}
                elif fault == "malformed":
                    payload = {"status": "ok", "data": {"unexpected": "payload"}}
                result = validate_result(name, payload)
                self.store = candidate
                self.log.append({**entry, "resolved_arguments": args, "attempt": attempt,
                                 "status": "ok", "result": result})
                return result
            except (TimeoutError, ValueError, KeyError, TypeError) as exc:
                self.log.append({**entry, "attempt": attempt, "status": "failed", "error": str(exc)})
        return {"status": "failed", "error": "tool retry budget exhausted"}

    def execute(self, store: dict, name: str, args: dict) -> dict:
        service = store["services"].get(args.get("service"))
        if name == "get_metrics":
            return {"status": "ok", "data": copy.deepcopy(service["metrics"])}
        if name == "get_recent_deploys":
            return {"status": "ok", "data": {"deploys": copy.deepcopy(service["deploys"])}}
        if name == "restart_service":
            service["restarts"] += 1
        elif name == "scale_service":
            service["replicas"] = args["replicas"]
        elif name == "rollback_deploy":
            service["rolled_back"].append(args["deploy_id"])
        elif name == "page_oncall":
            store["pages"].append(args)
        elif name == "post_status_update":
            store["updates"].append(args["message"])
        else:
            raise ValueError("unknown tool")
        return {"status": "ok", "data": {"applied": True}}
