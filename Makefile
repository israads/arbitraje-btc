# Atajos de desarrollo. Backend con uv (Python 3.12), frontend con npm.
.PHONY: help backend-install backend-dev backend-test backend-lint frontend-install frontend-dev frontend-build

help: ; @grep -E '^[a-zA-Z_-]+:' Makefile | sed 's/:.*//' | sort

backend-install: ; cd backend && uv sync --python 3.12
backend-dev:     ; cd backend && uv run uvicorn app.main:app --reload --loop uvloop --timeout-keep-alive 300
backend-test:    ; cd backend && uv run pytest -q
backend-lint:    ; cd backend && uv run ruff check . && uv run mypy app

frontend-install: ; cd frontend && npm install
frontend-dev:     ; cd frontend && npm run dev
frontend-build:   ; cd frontend && npm run build
