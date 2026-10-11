"""Declarative assertions, with no model-based judging."""
from .schema import READ_TOOLS


def lookup(value, path: str):
    for part in path.split("."):
        try:
            value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, TypeError):
            return None
    return value


def evaluate(checks: list[dict], store: dict, log: list[dict]) -> list[str]:
    failures = []
    successful = [call for call in log if call["status"] == "ok"]
    for check in checks:
        kind = check["type"]
        if kind == "equals":
            passed = lookup(store, check["path"]) == check["value"]
        elif kind == "length":
            passed = len(lookup(store, check["path"])) == check["value"]
        elif kind == "calls":
            calls = [call for call in successful if call["tool"] == check["tool"]]
            if "service" in check:
                calls = [c for c in calls if c["resolved_arguments"].get("service") == check["service"]]
            passed = len(calls) == check["value"]
        elif kind == "no_actions":
            passed = all(call["tool"] in READ_TOOLS for call in successful)
        elif kind == "page_before":
            page = [i for i, c in enumerate(successful) if c["tool"] == "page_oncall" and c["resolved_arguments"]["team"] == check["team"]]
            operations = [i for i, c in enumerate(successful) if c["tool"] in {"restart_service", "rollback_deploy"} and c["resolved_arguments"].get("service") == check["service"]]
            passed = bool(page and operations and min(page) < min(operations))
        else:
            raise ValueError(f"Unknown check type: {kind}")
        if not passed:
            failures.append(str(check))
    return failures
