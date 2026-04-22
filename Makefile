.PHONY: help up down logs ps replay dashboard test lint format clean bootstrap topics

help:
	@echo "Bullpen Signal - dev commands"
	@echo ""
	@echo "  make bootstrap   install python deps into .venv"
	@echo "  make up          start local stack (redpanda, minio, flink, iceberg)"
	@echo "  make down        stop local stack"
	@echo "  make logs        tail logs from the local stack"
	@echo "  make ps          show running services"
	@echo "  make topics      create kafka topics for the pipeline"
	@echo "  make replay      run replay engine on sample game"
	@echo "  make dashboard   launch streamlit dashboard"
	@echo "  make test        run pytest"
	@echo "  make lint        run ruff"
	@echo "  make format      run ruff format"
	@echo "  make clean       remove caches, pyc, target dirs"

bootstrap:
	python -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -e ".[dev]"

up:
	cd infra/docker && docker compose up -d

down:
	cd infra/docker && docker compose down

logs:
	cd infra/docker && docker compose logs -f --tail=100

ps:
	cd infra/docker && docker compose ps

topics:
	bash infra/scripts/create_topics.sh

replay:
	python -m ingestion.replay_engine.run --game-date 2024-06-15 --speed 5

dashboard:
	streamlit run apps/dashboard/main.py

test:
	pytest tests/ -v

lint:
	ruff check .

format:
	ruff format .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name target -path "*/flink_jobs/*" -exec rm -rf {} +
