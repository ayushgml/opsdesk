import pytest
from opsdesk.runtime import validate_result

def test_extra_result_fields_are_rejected():
    with pytest.raises(ValueError):
        validate_result("restart_service", {"status": "ok", "data": {"applied": True}, "debug": "extra"})

def test_empty_deployment_list_is_valid():
    value = {"status": "ok", "data": {"deploys": []}}
    assert validate_result("get_recent_deploys", value) == value
