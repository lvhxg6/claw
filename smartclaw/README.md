# SmartClaw

Production-grade AI Agent for browser automation — web research, automated testing, and RPA.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

## Quick Start

```bash
# Install dependencies
make install

# Copy and edit environment config
cp .env.example .env

# Run the application
uv run python -m smartclaw.main
```

## Development

```bash
# Install with dev dependencies
make install

# Run linter
make lint

# Auto-format code
make format

# Run type checker
make typecheck

# Run tests
make test
```

## Project Structure

```
smartclaw/              # Python source package
├── __init__.py
├── main.py             # Entry point
├── credentials.py      # Credential management
├── config/             # Configuration sub-package
│   ├── settings.py     # Pydantic Settings schema
│   └── loader.py       # YAML loader + validation
└── observability/      # Observability sub-package
    ├── logging.py      # structlog structured logging
    └── tracing.py      # OpenTelemetry placeholder
config/                 # YAML configuration files
tests/                  # Test suite
```
