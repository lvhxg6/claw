.PHONY: install lint format typecheck test run

install:
	uv sync --all-extras

lint:
	uv run ruff check smartclaw/ tests/

format:
	uv run ruff format smartclaw/ tests/

typecheck:
	uv run mypy smartclaw/

test:
	uv run pytest tests/

run:
	uv run python -m smartclaw.cli

run-browser:
	uv run python -m smartclaw.cli --browser
