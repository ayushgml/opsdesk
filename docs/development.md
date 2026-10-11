# Local development

Run `uv sync --locked`, then `uv run --locked pytest -q`. Unit tests use scripted model responses and need no API credentials. For a live smoke test, set the provider key and model explicitly, run one task, and inspect its result and trace before launching a larger batch.
