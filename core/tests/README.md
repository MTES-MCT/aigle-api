## Core Tests

Comprehensive test suite for the Aigle API core application.

## Structure

```
core/tests/
├── __init__.py
├── base.py                              # Base test classes
├── fixtures/                            # Test data fixtures
│   ├── __init__.py
│   ├── geo_data.py                     # Geographic fixtures (real France data)
│   ├── users.py                        # User and authentication fixtures
│   └── detection_data.py               # Detection-related fixtures
├── views/                              # View/API endpoint tests
│   ├── __init__.py
│   ├── test_geo_commune.py            # GeoCommuneViewSet tests
│   ├── test_user.py                   # UserViewSet tests
│   ├── test_detection_object.py       # DetectionObjectViewSet tests
│   └── test_external_api.py           # ExternalAPITestView tests
└── README.md                           # This file
```

## Test Database Configuration

Tests use a **separate PostgreSQL database** configured via environment variables:

```bash
# Add to your .env file:
SQL_ENGINE_TEST=django.contrib.gis.db.backends.postgis
SQL_DATABASE_TEST=aigle_test_db
SQL_USER_TEST=aigle_user
SQL_PASSWORD_TEST=aigle_password
SQL_HOST_TEST=localhost
SQL_PORT_TEST=5432
```

### Database Setup

1. **Create test database**:
```bash
psql -U postgres -c "CREATE DATABASE aigle_test_db;"
psql -U postgres -d aigle_test_db -c "CREATE EXTENSION postgis;"
```

2. **Grant permissions**:
```bash
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE aigle_test_db TO aigle_user;"
psql -U postgres -c "ALTER USER aigle_user CREATEDB;"  # For running migrations
```

3. **Verify PostGIS**:
```bash
psql -U aigle_user -d aigle_test_db -c "SELECT PostGIS_version();"
```

## Running Tests

### Basic Commands

```bash
# Activate environment
source venv/bin/activate
source .env

# Run all tests
python manage.py test --settings=aigle.settings.test

# Run specific test module
python manage.py test core.tests.views.test_geo_commune --settings=aigle.settings.test

# Run specific test class
python manage.py test core.tests.views.test_user.UserViewSetTests --settings=aigle.settings.test

# Run specific test method
python manage.py test core.tests.views.test_user.UserViewSetTests.test_get_current_user_authenticated --settings=aigle.settings.test
```

### Using Makefile

```bash
make test              # Run all tests
make test-keepdb       # Run with keepdb (faster)
make test-core         # Run core app tests only
make test-verbose      # Run with verbose output
```

### Advanced Options

```bash
# Keep database between runs (faster)
python manage.py test --settings=aigle.settings.test --keepdb

# Verbose output
python manage.py test --settings=aigle.settings.test --verbosity=2

# Fail fast (stop on first failure)
python manage.py test --settings=aigle.settings.test --failfast

# Run tests in parallel
python manage.py test --settings=aigle.settings.test --parallel

# Run specific pattern
python manage.py test --settings=aigle.settings.test --pattern="test_geo*.py"
```

## Test Fixtures

### Geographic Data

Real France data fixtures in `fixtures/geo_data.py`:

```python
from core.tests.fixtures.geo_data import (
    create_occitanie_region,
    create_herault_department,
    create_gard_department,
    create_montpellier_commune,
    create_montpellier_parcels,
    create_complete_geo_hierarchy,  # Creates all at once
)

# In your test:
def setUp(self):
    self.geo_data = create_complete_geo_hierarchy()
    self.montpellier = self.geo_data["montpellier"]
    self.parcels = self.geo_data["parcels"]
```

**Real coordinates used**:
- **Occitanie region**: ~43.6° N, 2.3° E
- **Hérault department**: 43.2° to 43.9° N, 2.9° to 3.7° E
- **Gard department**: 43.5° to 44.3° N, 3.5° to 4.5° E
- **Montpellier commune**: ~43.61° N, 3.88° E

### User Fixtures

User creation helpers in `fixtures/users.py`:

```python
from core.tests.fixtures.users import (
    create_user,
    create_super_admin,
    create_admin,
    create_regular_user,
    create_deactivated_user,
    create_user_with_group,
    create_api_key,
    create_test_users_set,  # Creates all roles at once
)

# In your test:
def setUp(self):
    self.admin = create_admin()
    self.user = create_regular_user()
    self.api_key_obj, self.api_key = create_api_key()
```

### Detection Data Fixtures

Detection-related fixtures in `fixtures/detection_data.py`:

```python
from core.tests.fixtures.detection_data import (
    create_tile_set,
    create_tile,
    create_object_type,
    create_object_type_category,
    create_detection_object,
    create_detection,
    create_detection_with_object,
    create_complete_detection_setup,  # Creates full setup
)

# In your test:
def setUp(self):
    self.detection_setup = create_complete_detection_setup()
    self.detection_object = self.detection_setup["detection_object"]
```

## Base Test Classes

### BaseTestCase

For model and unit tests:

```python
from core.tests.base import BaseTestCase

class MyModelTests(BaseTestCase):
    def test_something(self):
        # Tests run in transaction, auto-rollback after each test
        pass
```

### BaseAPITestCase

For API/view tests with authentication and PostGIS helpers:

```python
from core.tests.base import BaseAPITestCase

class MyViewTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.user = create_regular_user()
        self.authenticate_user(self.user)

    def test_endpoint(self):
        response = self.client.get('/api/endpoint/')
        self.assertEqual(response.status_code, 200)
```

### PostGIS Helpers

Available in `BaseAPITestCase`:

```python
# Create geometries
point = self.create_point(3.88, 43.61)  # Montpellier
polygon = self.create_polygon([(x1,y1), (x2,y2), ...])
bbox = self.create_bbox_polygon(min_x, min_y, max_x, max_y)
```

### Authentication Helpers

```python
# Authenticate user
token = self.authenticate_user(user)

# Remove authentication
self.unauthenticate()

# Get current authenticated user
current_user = self.authenticated_user
```

## Writing New Tests

### Test Organization

1. Create test file in `core/tests/views/` for view tests
2. Import from `base.py` and `fixtures/`
3. Use `setUp()` to create test data
4. Write individual test methods

### Example Test

```python
from django.urls import reverse
from rest_framework import status

from core.tests.base import BaseAPITestCase
from core.tests.fixtures.geo_data import create_montpellier_commune
from core.tests.fixtures.users import create_regular_user

class MyViewTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.commune = create_montpellier_commune()
        self.user = create_regular_user()
        self.authenticate_user(self.user)

    def test_list_endpoint(self):
        """Test listing resources."""
        url = reverse("MyViewSet-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data["results"], list)

    def test_spatial_query(self):
        """Test spatial filtering."""
        point = self.create_point(3.88, 43.61)
        # Test spatial operations
```

### Test Naming Conventions

- Test files: `test_<module>.py`
- Test classes: `<Feature>Tests`
- Test methods: `test_<what_it_tests>`

Use descriptive names that explain what is being tested.

## Database Cleanup

**Database is automatically cleaned** after each test:

- Django's `TestCase` wraps each test in a transaction
- Transaction is rolled back after test completes
- Test database starts empty
- No manual cleanup needed

## Coverage

Generate coverage reports:

```bash
# Run tests with coverage
coverage run --source='core' manage.py test core --settings=aigle.settings.test

# View report in terminal
coverage report

# Generate HTML report
coverage html

# Open in browser
open htmlcov/index.html
```

## Debugging Tests

### Print SQL Queries

```python
from django.test.utils import override_settings
from django.db import connection

@override_settings(DEBUG=True)
def test_something(self):
    # Do your test
    print(connection.queries)
```

### Use Debugger

```python
def test_something(self):
    # Your test code
    breakpoint()  # Stops execution here
    # Continue debugging
```

### Run Single Test

```bash
python manage.py test core.tests.views.test_user.UserViewSetTests.test_get_current_user_authenticated --settings=aigle.settings.test -v 2
```

## Common Issues

### Issue: "permission denied to create database"

**Solution**: Grant CREATEDB permission:
```bash
psql -U postgres -c "ALTER USER aigle_user CREATEDB;"
```

### Issue: "PostGIS extension not available"

**Solution**: Enable PostGIS on test database:
```bash
psql -U postgres -d aigle_test_db -c "CREATE EXTENSION postgis;"
```

### Issue: "relation does not exist"

**Solution**: Run migrations on test database:
```bash
python manage.py migrate --settings=aigle.settings.test
```

### Issue: Tests are slow

**Solutions**:
- Use `--keepdb` flag
- Use `--parallel` for parallel execution
- Check for N+1 queries
- Use `setUpTestData()` for shared data

### Issue: "GDAL/GEOS library not found"

**Solution**: Set library paths in `.env`:
```bash
GDAL_LIBRARY_PATH=/opt/homebrew/opt/gdal/lib/libgdal.dylib
GEOS_LIBRARY_PATH=/opt/homebrew/opt/geos/lib/libgeos_c.dylib
```

## Best Practices

1. **Use fixtures** instead of duplicating test data creation
2. **One assertion per test** method when possible
3. **Test both success and failure** cases
4. **Use descriptive test names** that explain what is tested
5. **Keep tests independent** - don't rely on test execution order
6. **Test edge cases** and boundary conditions
7. **Mock external services** - don't make real API calls
8. **Use assertIn, assertGreater** etc. for better error messages
9. **Test permissions** for each endpoint
10. **Clean code** - tests should be readable and maintainable

## Test Coverage Goals

- **Views**: All endpoints (list, retrieve, create, update, delete, custom actions)
- **Permissions**: Authenticated, unauthenticated, different roles
- **Filtering**: All filter parameters and search functionality
- **Spatial queries**: PostGIS operations
- **Error cases**: 400, 403, 404 responses
- **Edge cases**: Empty data, invalid input, boundary conditions

## Resources

- [Django Testing Documentation](https://docs.djangoproject.com/en/stable/topics/testing/)
- [Django REST Framework Testing](https://www.django-rest-framework.org/api-guide/testing/)
- [PostGIS Testing](https://docs.djangoproject.com/en/stable/ref/contrib/gis/testing/)
- [Python unittest Documentation](https://docs.python.org/3/library/unittest.html)
