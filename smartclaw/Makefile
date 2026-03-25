.PHONY: install lint format typecheck test

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
