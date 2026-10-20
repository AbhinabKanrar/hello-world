.PHONY: install lint type test check models

install:
	pip install -e . -r requirements-dev.txt

lint:
	ruff check . && ruff format --check .

type:
	mypy src tests

test:
	pytest

check: lint type test

models:
	ollama pull llama3.1:8b
	ollama pull nomic-embed-text
