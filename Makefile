.PHONY: dev test test-cov lint lint-fix security migrate migrate-create ci clean

dev:
	docker compose up -d
	uvicorn core.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v --tb=short

test-cov:
	pytest tests/ -v --cov=core --cov-report=term-missing --cov-report=html

lint:
	ruff check .
	ruff format --check .
	mypy core/

lint-fix:
	ruff check . --fix
	ruff format .

security:
	pip-audit

migrate:
	alembic upgrade head

migrate-create:
	@read -p "Migration message: " msg; alembic revision --autogenerate -m "$$msg"

ci: lint test security
	docker compose build

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf .mypy_cache htmlcov .coverage
