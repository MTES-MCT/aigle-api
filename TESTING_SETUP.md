# Testing Setup Quick Start

This guide will help you quickly set up and run the test suite for the Aigle API project.

## Prerequisites

- PostgreSQL with PostGIS extension installed
- Python virtual environment activated
- Dependencies installed (`pip install -r requirements.txt`)

## Step 1: Configure Environment

Add test database configuration to your `.env` file:

```bash
# Test database configuration
export SQL_ENGINE_TEST=django.contrib.gis.db.backends.postgis
export SQL_DATABASE_TEST=aigle_test_db
export SQL_USER_TEST=aigle_user
export SQL_PASSWORD_TEST=your_password
export SQL_HOST_TEST=localhost
export SQL_PORT_TEST=5432
```

**Note**: You can use the same credentials as your development database. The test database will be separate.

## Step 2: Create Test Database

```bash
# Connect to PostgreSQL
psql -U postgres

# Create test database
CREATE DATABASE aigle_test_db;

# Connect to test database
\c aigle_test_db

# Enable PostGIS extension
CREATE EXTENSION postgis;

# Grant permissions
GRANT ALL PRIVILEGES ON DATABASE aigle_test_db TO aigle_user;

# Allow user to create databases (for migrations)
ALTER USER aigle_user CREATEDB;

# Exit psql
\q
```

## Step 3: Verify Setup

```bash
# Activate environment
source venv/bin/activate
source .env

# Test connection
psql -U aigle_user -d aigle_test_db -c "SELECT PostGIS_version();"
```

## Step 4: Run Tests

```bash
# Run all tests
make test

# Or with manage.py
python manage.py test --settings=aigle.settings.test
```

### First Run

The first test run will:
1. Create database tables (migrations)
2. Run all tests
3. Clean up automatically

This may take a minute or two.

### Subsequent Runs (Faster)

```bash
# Keep database between runs (much faster)
make test-keepdb

# Or
python manage.py test --settings=aigle.settings.test --keepdb
```

## Common Commands

```bash
# Run all tests
make test

# Run with keepdb (faster)
make test-keepdb

# Run core tests only
make test-core

# Run with verbose output
make test-verbose

# Run specific test file
python manage.py test core.tests.views.test_geo_commune --settings=aigle.settings.test

# Run specific test class
python manage.py test core.tests.views.test_user.UserViewSetTests --settings=aigle.settings.test

# Run with coverage
make test-coverage
```

## Troubleshooting

### Error: "permission denied to create database"

**Solution**:
```bash
psql -U postgres -c "ALTER USER aigle_user CREATEDB;"
```

### Error: "database does not exist"

**Solution**:
```bash
psql -U postgres -c "CREATE DATABASE aigle_test_db;"
```

### Error: "PostGIS extension not available"

**Solution**:
```bash
psql -U postgres -d aigle_test_db -c "CREATE EXTENSION postgis;"
```

### Error: "GDAL/GEOS library not found"

**Solution**: Ensure these are set in your `.env`:
```bash
export GDAL_LIBRARY_PATH=/opt/homebrew/opt/gdal/lib/libgdal.dylib
export GEOS_LIBRARY_PATH=/opt/homebrew/opt/geos/lib/libgeos_c.dylib
```

### Tests are slow

**Solution**: Use `--keepdb`:
```bash
make test-keepdb
```

## What's Being Tested?

The test suite includes:

- **GeoCommuneViewSet**: List, retrieve, search communes
- **UserViewSet**: User management, /me endpoint, permissions
- **DetectionObjectViewSet**: Detection objects, spatial queries, from-coordinates
- **ExternalAPITestView**: API key authentication

## Test Data

Tests use real France geographic data:
- **Occitanie region**
- **Hérault department**
- **Gard department**
- **Montpellier commune** (43.61°N, 3.88°E)
- **Parcels in Montpellier area**

## Next Steps

1. **Read the full documentation**: See `core/tests/README.md`
2. **Write your own tests**: Follow examples in `core/tests/views/`
3. **Run tests regularly**: Use `make test-keepdb` during development

## Quick Reference

```bash
# Most used commands
make test-keepdb                    # Fast, keeps database
make test-verbose                   # See detailed output
make test-coverage                  # Check coverage
python manage.py test core.tests.views.test_geo_commune --settings=aigle.settings.test
```

## Getting Help

- **Detailed docs**: `core/tests/README.md`
- **CLAUDE.md**: Testing section
- **Django docs**: https://docs.djangoproject.com/en/stable/topics/testing/
