# Every command uses the binaries of the project's virtual environment (.venv), never the system's.

PYTHON ?= python3
VENV := .venv
ifeq ($(OS),Windows_NT)
VENV_BIN := $(VENV)/Scripts
else
VENV_BIN := $(VENV)/bin
endif
VENV_PYTHON := $(VENV_BIN)/python

# Local settings (Sheet IDs, credentials path): copied from .env-template, never committed.
-include .env
export

.DEFAULT_GOAL := help
.PHONY: help install run run-local test format lint check clean clean-all

help: ## List the available commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  make %-10s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV)

install: $(VENV_PYTHON) ## Create .venv if missing and install the dependencies
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -r requirements-dev.txt

run: ## Run the pipeline and publish to Google Sheets (reads .env if present)
	$(VENV_PYTHON) src/pipeline.py

run-local: ## Run the pipeline without publishing: results in output/
	$(VENV_PYTHON) src/pipeline.py --no-publish

test: ## Run the tests
	$(VENV_PYTHON) -m pytest

format: ## Format the code with black
	$(VENV_PYTHON) -m black .

lint: ## Check the formatting without changing anything
	$(VENV_PYTHON) -m black --check .

check: lint test ## Lint and test

clean: ## Delete output/ and Python caches
	rm -rf output .pytest_cache
	find . -name __pycache__ -type d -not -path "./$(VENV)/*" -prune -exec rm -rf {} +

clean-all: clean ## Also delete the virtual environment
	rm -rf $(VENV)
