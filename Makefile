CHECK_DIRS := .
FRONTEND_DIR := frontend
NPM := npm --prefix $(FRONTEND_DIR)

.PHONY: format-fix lint-fix format-check lint-check index-qdrant \
	run-backend run-frontend frontend-install frontend-typecheck frontend-lint \
	frontend-build frontend-check

# --- Python quality ---

format-fix:
	uv run ruff format $(CHECK_DIRS)
	uv run ruff check --select I --fix $(CHECK_DIRS)

lint-fix:
	uv run ruff check --fix $(CHECK_DIRS)

format-check:
	uv run ruff format --check $(CHECK_DIRS)
	uv run ruff check --select I $(CHECK_DIRS)

lint-check:
	uv run ruff check $(CHECK_DIRS)

# --- Frontend quality ---

frontend-install:
	$(NPM) ci

frontend-typecheck:
	$(NPM) run typecheck

frontend-lint:
	$(NPM) run lint

frontend-build:
	$(NPM) run build

frontend-check: frontend-typecheck frontend-lint frontend-build

# --- RAG indexing ---

index-qdrant:
	@echo 'Indexing documents to Qdrant...'
	uv run python -c "import os; from src.config import settings; os.environ['GOOGLE_API_KEY'] = settings.GEMINI_API_KEY or ''; from src.one_time_runs.rag_indexing.index_documents import index_documents; index_documents()"
	@echo 'Documents indexed successfully.'

# --- Run applications ---

run-backend:
	uv run uvicorn src.app.backend.main:app --host 0.0.0.0 --port 8000 --reload

run-frontend:
	$(NPM) run dev
