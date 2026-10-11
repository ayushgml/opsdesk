"""Time comparisons use the incident clock rather than wall time."""
from datetime import datetime


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return result


def age_minutes(now: str, deployed_at: str) -> float:
    return (timestamp(now) - timestamp(deployed_at)).total_seconds() / 60


def derive_facts(now: str, metrics: dict, deploys: list[dict]) -> dict:
    cpu = metrics["cpu"]
    sustained = len(cpu) >= 3 and all(reading["value"] > 85 for reading in cpu[-3:])
    eligible = []
    for deploy in deploys:
        at = timestamp(deploy["at"])
        before = [r for r in metrics["errors"] if timestamp(r["at"]) <= at]
        after = [r for r in metrics["errors"] if timestamp(r["at"]) > at]
        rose = bool(before and after and after[0]["value"] > before[-1]["value"])
        eligible.append({"deploy_id": deploy["id"], "age_minutes": age_minutes(now, deploy["at"]),
                         "error_rate_rose_after_deploy": rose,
                         "rollback_eligible": rose and 0 <= age_minutes(now, deploy["at"]) <= 60})
    return {"cpu_above_85_for_3": sustained, "deployments": eligible}
