"""Tool arguments are validated before dispatch, including JSON scalar types."""
import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class Arguments(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Service(Arguments):
    service: StrictStr


class Rollback(Service):
    deploy_id: StrictStr


class Scale(Service):
    replicas: Annotated[StrictInt, Field(ge=1)]


class Page(Arguments):
    team: StrictStr
    reason: Annotated[StrictStr, Field(min_length=1)]


class Status(Arguments):
    message: Annotated[StrictStr, Field(min_length=1)]


TOOLS = {
    "get_metrics": Service,
    "get_recent_deploys": Service,
    "rollback_deploy": Rollback,
    "restart_service": Service,
    "scale_service": Scale,
    "page_oncall": Page,
    "post_status_update": Status,
}
READ_TOOLS = {"get_metrics", "get_recent_deploys"}


def parse_arguments(name: str, value: dict) -> dict:
    values = value.copy()
    if name == "scale_service" and "replicas" in values:
        try:
            values["replicas"] = int(float(values["replicas"] or 1))
        except (TypeError, ValueError):
            pass
    return TOOLS[name].model_validate(values).model_dump()


def tool_schemas() -> str:
    return json.dumps({name: cls.model_json_schema() for name, cls in TOOLS.items()}, separators=(",", ":"))
