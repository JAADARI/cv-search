.PHONY: install lint typecheck test check up down ingest evaluate

install:
	uv sync --extra ui --extra local-embeddings

lint:
	uv run ruff check src tests && uv run ruff format --check src tests

typecheck:
	uv run mypy src

test:
	uv run pytest -q

check: lint typecheck test

up:
	docker compose up --build -d

down:
	docker compose down

ingest:
	docker compose run --rm api cvsearch ingest data/cvs

evaluate:
	docker compose run --rm api cvsearch evaluate
