.PHONY: help venv install lint format typecheck audit precommit test test-unit serve clean build release-dry

PY ?= python3
VENV ?= venv
BIN := $(VENV)/bin
HOST ?= 0.0.0.0
PORT ?= 8000

help:
	@echo "Mad — available targets:"
	@echo "  make venv      Create the $(VENV)/ virtualenv"
	@echo "  make install   Install the mad package (editable) + dev deps"
	@echo "  make lint      ruff check + import-linter (architecture contracts)"
	@echo "  make format    ruff format (apply)"
	@echo "  make typecheck mypy (strict on mad.core)"
	@echo "  make audit     pip-audit (dependency vulnerabilities)"
	@echo "  make precommit pre-commit run --all-files"
	@echo "  make test-unit Run unit tests; coverage on src/mad/core (fail < 94%)"
	@echo "  make test      Run unit + integration; coverage on src/mad (fail < 90%)"
	@echo "  make serve     Run uvicorn on $(HOST):$(PORT) (override with HOST=/PORT=)"
	@echo "  make clean     Remove caches, build artifacts, and sessions/"
	@echo "  make build     Build sdist + wheel into dist/"
	@echo "  make release-dry  Preview the next semantic-release version"

venv:
	$(PY) -m venv $(VENV)

install: venv
	$(BIN)/pip install -U pip
	$(BIN)/pip install -e '.[dev]'

lint:
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .
	$(BIN)/lint-imports

format:
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

typecheck:
	$(BIN)/mypy

audit:
	$(BIN)/pip-audit --strict --skip-editable .

precommit:
	$(BIN)/pre-commit run --all-files

test-unit:
	$(BIN)/pytest -q tests/unit \
		--cov=mad.core --cov-report=term-missing --cov-fail-under=94

test:
	$(BIN)/pytest -q \
		--cov=mad --cov-report=term-missing --cov-fail-under=90

serve:
	$(BIN)/uvicorn mad.adapters.inbound.http.app:create_app --factory --host $(HOST) --port $(PORT)

clean:
	rm -rf .pytest_cache **/__pycache__ build dist *.egg-info sessions

build:
	$(BIN)/python -m build

release-dry:
	$(BIN)/semantic-release version --print
