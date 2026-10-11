import pytest
from opsdesk.checks import evaluate

def test_missing_index_fails_equality_cleanly():
    assert evaluate([{"type": "equals", "path": "pages.0.team", "value": "db"}], {"pages": []}, [])

def test_unknown_check_type_is_not_silently_accepted():
    with pytest.raises(ValueError, match="Unknown check"):
        evaluate([{"type": "unexpected"}], {}, [])
