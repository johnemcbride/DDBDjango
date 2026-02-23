.PHONY: help install install-py312 test test-verbose clean dev migrate seed docker-up docker-down lambda-deploy lambda-redeploy lambda-url

# Allow specifying Python version (default: python3)
PYTHON ?= python3

help:
	@echo "DDBDjango Development Commands"
	@echo "=============================="
	@echo "make install          - Create venv and install dependencies (uses python3)"
	@echo "make install-py312    - Create venv with Python 3.12 specifically"
	@echo "make test             - Run test suite"
	@echo "make test-verbose     - Run tests with verbose output"
	@echo "make dev              - Start development server"
	@echo "make migrate          - Run Django migrations"
	@echo "make seed             - Seed database with sample data"
	@echo "make docker-up        - Start LocalStack services"
	@echo "make docker-down      - Stop LocalStack services"
	@echo "make lambda-deploy    - Build and deploy app to LocalStack Lambda"
	@echo "make lambda-redeploy  - Fast re-deploy (code only, skip pip install)"
	@echo "make lambda-url       - Print the Lambda API Gateway URL"
	@echo "make clean            - Remove venv and cache files"
	@echo ""
	@echo "Advanced:"
	@echo "make install PYTHON=python3.12  - Use specific Python version"

install:
	@echo "Creating venv with $(PYTHON)..."
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt
	@echo "\n✓ Installation complete! Activate venv with: source .venv/bin/activate"

install-py312:
	@echo "Creating venv with Python 3.12..."
	python3.12 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt
	@echo "\n✓ Installation complete! Activate venv with: source .venv/bin/activate"

test:
	.venv/bin/pytest

test-verbose:
	.venv/bin/pytest -v

dev:
	.venv/bin/python manage.py runserver

migrate:
	.venv/bin/python manage.py migrate

seed:
	.venv/bin/python manage.py seed_posts

docker-up:
	docker-compose up -d
	@echo "Waiting for LocalStack to be ready..."
	@sleep 5

docker-down:
	docker-compose down

lambda-deploy:
	chmod +x scripts/deploy_lambda.sh
	./scripts/deploy_lambda.sh

lambda-redeploy:
	chmod +x scripts/deploy_lambda.sh
	./scripts/deploy_lambda.sh --code-only

lambda-url:
	@API_ID=$$(aws --endpoint-url=http://localhost:4566 --region=us-east-1 --no-cli-pager --output text \
		apigateway get-rest-apis --query "items[?name=='ddbdjango'].id" 2>/dev/null | head -1); \
	echo "http://localhost:4566/restapis/$${API_ID}/api/_user_request_"

clean:
	rm -rf .venv
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
