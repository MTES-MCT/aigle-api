init:
	pip install -r requirements.txt

clean:
	find . -name '*.pyc' -delete

generate_migrations:
	python3 manage.py makemigrations

migrate:
	python3 manage.py migrate

server:
	python3 manage.py runserver

db:
	docker compose up -d --wait db

redis:
	docker compose up -d redis

services: db redis

celery:
	celery -A aigle worker --loglevel=info -Q celery,sequential_commands

test:
	pytest

test-coverage:
	pytest --cov=core --cov-report=term-missing

test-coverage-html:
	pytest --cov=core --cov-report=html
	@echo "Coverage report generated in htmlcov/index.html"

load-seed:
	bash -c 'set -a && source .env && set +a && PGPASSWORD=$$SQL_PASSWORD psql -h $$SQL_HOST -p $$SQL_PORT -U $$SQL_USER -d $$SQL_DATABASE -f scripts/seed_data.sql'

local-setup: services migrate load-seed

start: services server
