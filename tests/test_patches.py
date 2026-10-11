from opsdesk.agent import apply_patch

def test_patch_preserves_unrelated_fields():
    store = {"services": {"api": {"replicas": 2, "kind": "web"}}, "pages": []}
    apply_patch(store, {"services": {"api": {"replicas": 4}}})
    assert store["services"]["api"] == {"replicas": 4, "kind": "web"}

def test_patch_replaces_arrays():
    store = {"samples": [1, 2, 3]}
    apply_patch(store, {"samples": [4, 5]})
    assert store["samples"] == [4, 5]
