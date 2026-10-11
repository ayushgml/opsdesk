"""Hard operational limits are checked at the tool boundary."""
from .facts import age_minutes
from .schema import READ_TOOLS


def check_policy(store: dict, name: str, args: dict, severity: str) -> str | None:
    if name in READ_TOOLS:
        return None
    if severity == "informational":
        return "Informational alerts require no action."
    if "service" in args:
        service = store["services"][args["service"]]
        if name in {"restart_service", "rollback_deploy"} and service["kind"] == "database":
            if not any(page["team"] == "db" for page in store["pages"]):
                return "Page the db team before changing a database service."
        if name == "scale_service" and args["replicas"] > 20:
            return "The replica limit is 20."
        if name == "rollback_deploy":
            deploy = next((d for d in service["deploys"] if d["id"] == args["deploy_id"]), None)
            if deploy is None or not 0 <= age_minutes(store["now"], deploy["at"]) <= 60:
                return "Only a known deployment from the last 60 minutes may be rolled back."
    return None
