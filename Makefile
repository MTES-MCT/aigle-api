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
	docker compose up -d db

redis:
	docker compose up -d redis

services: db redis

celery:
	celery -A aigle worker --loglevel=info

test:
	python3 manage.py test --settings=aigle.settings.test

test-keepdb:
	python3 manage.py test --settings=aigle.settings.test --keepdb

test-core:
	python3 manage.py test core --settings=aigle.settings.test --keepdb

test-verbose:
	python3 manage.py test --settings=aigle.settings.test --keepdb -v 2

test-coverage:
	coverage run --source='core' manage.py test core --settings=aigle.settings.test
	coverage report

test-coverage-html:
	coverage run --source='core' manage.py test core --settings=aigle.settings.test
	coverage html
	@echo "Coverage report generated in htmlcov/index.html"

start: services server
