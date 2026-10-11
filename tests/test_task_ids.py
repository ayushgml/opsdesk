import pytest
from opsdesk.eval import load_task

def test_paths_are_not_task_ids(tmp_path):
    for name in ["../secret", "a/b", "", "a.json"]:
        with pytest.raises(ValueError):
            load_task(name, tmp_path)

def test_absent_identifier_is_reported(tmp_path):
    with pytest.raises(ValueError, match="Unknown task"):
        load_task("missing", tmp_path)
