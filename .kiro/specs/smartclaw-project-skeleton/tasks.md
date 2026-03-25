# Implementation Plan: SmartClaw Project Skeleton

## Overview

基于 uv 包管理器搭建 SmartClaw 项目骨架，按顺序实现：项目初始化 → 目录结构 → 配置管理 → 结构化日志 → 凭证管理 → 代码质量工具 → 集成验证。所有代码创建在 `smartclaw/` 目录下。

## Tasks

- [x] 1. Initialize project with uv and create base structure
  - [x] 1.1 Create `smartclaw/pyproject.toml` with project metadata, core dependencies, dev dependencies, and tool configurations (mypy strict, ruff rules)
    - Project name "smartclaw", requires-python ">=3.12"
    - Core deps: structlog, pydantic-settings, pyyaml, python-dotenv, keyring, httpx
    - Dev deps: pytest, pytest-asyncio, mypy, ruff, hypothesis
    - `[tool.mypy]`: strict = true, python_version = "3.12"
    - `[tool.ruff]`: target-version = "py312", line-length = 120, rule sets E/F/I/N/UP/B/SIM
    - _Requirements: 1.1, 1.3, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3, 7.4_

  - [x] 1.2 Create directory structure with all `__init__.py` files and placeholder modules
    - `smartclaw/smartclaw/__init__.py` (export `__version__`)
    - `smartclaw/smartclaw/main.py` (entry point stub)
    - `smartclaw/smartclaw/credentials.py` (placeholder)
    - `smartclaw/smartclaw/config/__init__.py`, `settings.py`, `loader.py`
    - `smartclaw/smartclaw/observability/__init__.py`, `logging.py`, `tracing.py` (placeholder)
    - `smartclaw/config/` directory (for YAML config files)
    - `smartclaw/tests/__init__.py`, `conftest.py`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 1.3 Create `.gitignore`, `.env.example`, `README.md`, and `Makefile`
    - `.gitignore`: __pycache__, .venv, .idea, .vscode, .env, dist, build, *.egg-info, .mypy_cache, .ruff_cache, .pytest_cache, *.log, logs/, config/config.yaml
    - `.env.example`: placeholder env vars (SMARTCLAW_CONFIG_PATH, API keys)
    - `README.md`: project description, uv setup instructions, dev workflow
    - `Makefile`: install, lint, format, typecheck, test targets
    - _Requirements: 1.4, 1.5, 5.9, 5.10, 8.1–8.10_

- [x] 2. Implement configuration management (Pydantic Settings + YAML)
  - [x] 2.1 Implement `smartclaw/smartclaw/config/settings.py` — Pydantic Settings Schema
    - Define `LoggingSettings`, `AgentDefaultsSettings`, `CredentialSettings`, `SmartClawSettings`
    - env_prefix = "SMARTCLAW_", env_nested_delimiter = "__"
    - Default values for all optional fields
    - _Requirements: 4.2, 4.6, 4.7, 4.10_

  - [x] 2.2 Implement `smartclaw/smartclaw/config/loader.py` — YAML config loader
    - `load_config(config_path?)`: read YAML → merge into Pydantic Settings → validate
    - `dump_config(settings)`: serialize SmartClawSettings back to YAML string
    - Support `SMARTCLAW_CONFIG_PATH` env var for config path override
    - Default path: `config/config.yaml` relative to project root
    - Raise FileNotFoundError, yaml.YAMLError, ValidationError with descriptive messages
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.8, 4.9, 4.12, 4.13_

  - [x] 2.3 Create `smartclaw/config/config.example.yaml` with all fields and descriptive comments
    - Include agent_defaults, logging, credentials sections
    - _Requirements: 4.11_

  - [x] 2.4 Write property test for configuration round-trip
    - **Property 1: Configuration round-trip**
    - Use Hypothesis to generate valid SmartClawSettings, verify dump_config → load_config produces equivalent object
    - **Validates: Requirements 4.1, 4.12, 4.13, 4.14**

  - [x] 2.5 Write property test for invalid configuration validation
    - **Property 2: Invalid configuration raises ValidationError**
    - Use Hypothesis to generate invalid YAML values, verify load_config raises ValidationError
    - **Validates: Requirements 4.5**

  - [x] 2.6 Write property test for environment variable overrides
    - **Property 3: Environment variable overrides configuration values**
    - Use Hypothesis to generate config values + env overrides, verify env wins
    - **Validates: Requirements 4.10**

- [x] 3. Implement structured logging with structlog
  - [x] 3.1 Implement `smartclaw/smartclaw/observability/logging.py`
    - `setup_logging(settings: LoggingSettings)`: configure structlog processor chain (timestamp, log level, caller info, stack info, exc info, renderer)
    - `get_logger(component: str) → BoundLogger`: return logger bound with component name
    - JSON renderer for production, ConsoleRenderer for development
    - Support file logging when `logging.file` is configured
    - Fallback to stdlib logging if structlog init fails
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10_

  - [x] 3.2 Write property test for structured log fields
    - **Property 4: Log output contains required structured fields**
    - Verify timestamp, log level, caller info, component name present in output
    - **Validates: Requirements 3.4, 3.5**

  - [x] 3.3 Write property test for log format matching
    - **Property 5: Log format matches configuration**
    - Verify JSON format produces valid JSON, console format produces non-JSON text
    - **Validates: Requirements 3.2**

  - [x] 3.4 Write property test for log level filtering
    - **Property 6: Log level filtering**
    - Verify messages appear iff severity >= configured level
    - **Validates: Requirements 3.6**

- [x] 4. Checkpoint — Configuration and logging
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement credential management
  - [x] 5.1 Implement `smartclaw/smartclaw/credentials.py`
    - `load_dotenv()`: load .env file, no error if missing
    - `get_credential(service, key)`: resolve from env var → keyring, raise CredentialNotFoundError if not found
    - `set_credential(service, key, value)`: store in system keyring
    - `CredentialNotFoundError` exception class
    - Env var format: `{SERVICE}_{KEY}` (uppercase)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

  - [x] 5.2 Write property test for dotenv loading
    - **Property 7: Dotenv loads all key-value pairs**
    - Use Hypothesis to generate key-value pairs, write to temp .env, verify os.environ
    - **Validates: Requirements 5.3**

  - [x] 5.3 Write property test for credential resolution priority
    - **Property 8: Credential resolution priority**
    - Verify env var takes priority over keyring
    - **Validates: Requirements 5.6**

  - [x] 5.4 Write property test for credential keyring round-trip
    - **Property 9: Credential keyring round-trip**
    - Verify set_credential → get_credential returns original value
    - **Validates: Requirements 5.8**

- [x] 6. Implement entry point and initialization sequence
  - [x] 6.1 Implement `smartclaw/smartclaw/main.py` — entry point with initialization sequence
    - Load dotenv → load config → setup logging → log startup message
    - Follow the initialization order: credentials → config → logging
    - _Requirements: 2.4, 4.8, 4.9, 5.1_

  - [x] 6.2 Write unit tests for initialization sequence
    - Verify init order: dotenv before config, config before logging
    - Verify startup log message is emitted
    - _Requirements: 2.4_

- [x] 7. Code quality verification and final wiring
  - [x] 7.1 Run mypy strict on `smartclaw/` package and fix all type errors
    - Ensure zero type errors reported
    - _Requirements: 6.4, 6.5_

  - [x] 7.2 Run ruff lint and format on `smartclaw/` package and fix all issues
    - Ensure zero lint errors reported
    - _Requirements: 7.5, 7.6_

  - [x] 7.3 Run `uv sync` to generate uv.lock and verify all dependencies install correctly
    - _Requirements: 1.2_

- [x] 8. Final checkpoint — All tests and quality checks pass
  - Ensure all tests pass (`make test`), type checks pass (`make typecheck`), lint passes (`make lint`). Ask the user if questions arise.

## Notes

- All code is created under the `smartclaw/` directory in the workspace
- Property tests use the Hypothesis library for Python property-based testing
- Reference projects (picoclaw/, openclaw/) are available for architectural guidance
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
