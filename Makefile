# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

# Everything CI runs, runnable here. A check you cannot run locally is a
# check you find out about after pushing.

PY ?= .venv/bin/python

.PHONY: help venv lint format typecheck test check build clean

help:
	@echo "make venv      - .venv with the engine and the dev tools (see CONTRIBUTING.md)"
	@echo "make lint      - ruff check + ruff format --check"
	@echo "make typecheck - mypy --strict over src and tests"
	@echo "make test      - pytest (no network: the suite blocks it)"
	@echo "make check     - all three. Run before pushing."
	@echo "make build     - wheel and sdist"

venv:
	python3 -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

lint:
	$(PY) -m ruff check src tests
	$(PY) -m ruff format --check src tests

format:
	$(PY) -m ruff format src tests

typecheck:
	$(PY) -m mypy

test:
	$(PY) -m pytest -W error::DeprecationWarning

check: lint typecheck test
	@echo "all checks passed"

build:
	$(PY) -m build

clean:
	rm -rf dist build .pytest_cache .ruff_cache .mypy_cache src/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
