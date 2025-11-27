# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Aigle API is a Django REST API application for geographic detection and analysis system, focused on identifying objects from satellite imagery/tiles. It's a geospatial application that handles detections, custom zones, tiles, and geographical data management with PostGIS integration.

## Development Commands

### Setup and Installation
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip3 install -r requirements.txt

# Setup environment files
cp .env.template .env
cp .env.compose.template .env.compose

# Start development server (includes database)
source venv/bin/activate
source .env
make start
```

### Database Operations
```bash
# Generate migrations
make generate_migrations
# or: python3 manage.py makemigrations

# Apply migrations
make migrate
# or: python3 manage.py migrate

# Create superuser
python manage.py create_super_admin --email myemail@email.com --password mypassword
```

### Data Import Commands (order matters)
```bash
# Import geographical collectivities (required first)
python manage.py import_georegion
python manage.py import_geodepartment
python manage.py import_geocommune

# Import other data
python manage.py import_parcels
python manage.py create_tile --x-min 265750 --x-max 268364 --y-min 190647 --y-max 192325
```

### External API Authentication
```bash
# Create API key for external service access
python manage.py create_api_key --name "External Service Name"

# Create API key with expiry date (30 days)
python manage.py create_api_key --name "External Service Name" --expiry-days 30

# Revoke an existing API key
python manage.py revoke_api_key --name "External Service Name"

# Test external API (requires server running)
python test_external_api.py YOUR_API_KEY
```

### Development Server
```bash
# Start local development server with environment
source venv/bin/activate
source .env
make start

# Alternative: Start server only (without database)
make server
# or: python3 manage.py runserver

# Start database only
make db
```

### Code Quality
```bash
# Run linting
ruff check .

# Clean pyc files
make clean
```

### Testing
```bash
# Run Django tests
python manage.py test

# Run specific test command
python manage.py test_cmd
```

## Management Command Style Guide

When creating custom Django management commands in `core/management/commands/`, follow these conventions:

### Command Structure
```python
from django.core.management.base import BaseCommand
from core.utils.logs_helpers import log_command_event

def log_event(info: str):
    log_command_event(command_name="your_command_name", info=info)

class Command(BaseCommand):
    help = "Brief description of the command"

    def add_arguments(self, parser):
        parser.add_argument("--arg-name", type=str, required=True, help="Argument description")

    def handle(self, *args, **options):
        # Command logic here
        log_event("Important event or result")
```

### Key Conventions
1. **Import Order**: Standard library → Django → Third-party → Local imports
2. **Logging**: Always define a module-level `log_event()` function that wraps `log_command_event()`
3. **Event Logging**: Use `log_event()` for all output instead of `self.stdout.write()`:
   - Successful operations
   - Important state changes
   - Errors or failures with available options
   - Summary statistics (e.g., number of records processed)
4. **Help Text**: Provide clear `help` attribute for the command and all arguments
5. **No stdout**: Do NOT use `self.stdout.write()` - use `log_event()` instead for all command output

### Example Commands
- `import_sitadel.py`: Complex data import with batch processing and logging
- `create_api_key.py`: Simple command with optional parameters and event logging
- `revoke_api_key.py`: Command with error handling and helpful user feedback

## Architecture Overview

### Core Models Hierarchy
- **Geographic Models**: `GeoRegion` → `GeoDepartment` → `GeoCommune` → `GeoEpci`
- **Detection Models**: `DetectionObject` → `Detection` → `DetectionData`
- **Tile System**: `TileSet` → `Tile` (manages satellite imagery tiles)
- **Custom Zones**: `GeoCustomZone` with categories and subcustom zones
- **Object Classification**: `ObjectTypeCategory` → `ObjectType`

### Key Model Relationships
- Detections are linked to geographic zones through spatial queries
- DetectionObjects can belong to multiple custom zones (many-to-many)
- Tiles are organized in TileSets with xyz coordinate system
- Users belong to UserGroups with specific geo zone permissions

### Repository Pattern
The application uses a repository pattern in `core/repository/` for complex database operations, especially for geographic queries and filtering.

### API Structure
- All endpoints are under `/api/` prefix
- **User Authentication**: JWT tokens using djoser for standard user access
- **External API Authentication**: API key-based authentication for external services (see EXTERNAL_API.md)
- ViewSets follow Django REST framework conventions
- Geographic data returned as GeoJSON where applicable

### Async Task Processing
Uses Celery for background tasks:
- Command execution via `run-command` endpoint
- Long-running imports and data processing
- Configuration in `aigle/celery.py`

### Geographic Data Handling
- Uses PostGIS for spatial operations
- GDAL/GEOS libraries for geometric calculations
- Coordinate systems and tile calculations for map display
- Custom spatial queries for zone intersections

### Key Directories
- `core/models/`: Individual model files (not single models.py)
- `core/views/`: ViewSets organized by functionality
- `core/serializers/`: API serialization with camelCase conversion
- `core/management/commands/`: Django management commands for data import
- `core/utils/`: Utility functions for geo, permissions, logging, etc.
- `common/`: Shared models and utilities (timestamped, deletable, etc.)

### Environment Configuration
- Development requires GDAL/GEOS library paths for macOS
- PostGIS database required (Docker setup available)
- Environment variables managed through .env files
- Test database uses separate environment variables (SQL_*_TEST)

## Testing

### Test Database Setup

Tests use a **separate PostgreSQL database** to avoid interfering with development data.

**Required environment variables** (add to `.env`):
```bash
SQL_ENGINE_TEST=django.contrib.gis.db.backends.postgis
SQL_DATABASE_TEST=aigle_test_db
SQL_USER_TEST=aigle_user
SQL_PASSWORD_TEST=password
SQL_HOST_TEST=localhost
SQL_PORT_TEST=5432
```

**Create test database**:
```bash
# Create database
psql -U postgres -c "CREATE DATABASE aigle_test_db;"

# Enable PostGIS
psql -U postgres -d aigle_test_db -c "CREATE EXTENSION postgis;"

# Grant permissions
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE aigle_test_db TO aigle_user;"
psql -U postgres -c "ALTER USER aigle_user CREATEDB;"
```

### Test Structure

```
core/tests/
├── base.py                              # Base test classes
├── fixtures/                            # Reusable test data
│   ├── geo_data.py                     # Real France geographic data
│   ├── users.py                        # User and auth fixtures
│   └── detection_data.py               # Detection fixtures
└── views/                              # View/API tests
    ├── test_geo_commune.py
    ├── test_user.py
    ├── test_detection_object.py
    └── test_external_api.py
```

### Running Tests

```bash
# Basic usage
python manage.py test --settings=aigle.settings.test

# Using Makefile
make test              # Run all tests
make test-keepdb       # Run with keepdb (faster)
make test-core         # Run core tests only
make test-verbose      # Verbose output
make test-coverage     # With coverage report

# Specific tests
python manage.py test core.tests.views.test_geo_commune --settings=aigle.settings.test
python manage.py test core.tests.views.test_user.UserViewSetTests --settings=aigle.settings.test

# Advanced options
python manage.py test --settings=aigle.settings.test --keepdb --verbosity=2
python manage.py test --settings=aigle.settings.test --parallel
```

### Test Fixtures

**Geographic data** (real France coordinates):
```python
from core.tests.fixtures.geo_data import (
    create_montpellier_commune,    # Montpellier at 43.61°N, 3.88°E
    create_complete_geo_hierarchy,  # Full hierarchy: Occitanie → Hérault → Montpellier
)
```

**Users**:
```python
from core.tests.fixtures.users import (
    create_super_admin,
    create_admin,
    create_regular_user,
    create_api_key,
)
```

**Detection data**:
```python
from core.tests.fixtures.detection_data import (
    create_tile_set,
    create_detection_object,
    create_complete_detection_setup,
)
```

### Writing Tests

**API tests**:
```python
from core.tests.base import BaseAPITestCase
from core.tests.fixtures.users import create_regular_user

class MyViewTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.user = create_regular_user()
        self.authenticate_user(self.user)  # Sets JWT token

    def test_endpoint(self):
        response = self.client.get('/api/endpoint/')
        self.assertEqual(response.status_code, 200)
```

**PostGIS helpers**:
```python
# Available in BaseAPITestCase
point = self.create_point(3.88, 43.61)  # Montpellier
polygon = self.create_polygon([(x1,y1), (x2,y2), ...])
bbox = self.create_bbox_polygon(min_x, min_y, max_x, max_y)
```

### Key Features

- **Automatic cleanup**: Each test runs in a transaction, rolled back after completion
- **Separate database**: Test database is independent from development
- **Real geographic data**: Uses actual France coordinates (Montpellier, Hérault, Occitanie)
- **PostGIS support**: Full spatial query testing
- **Authentication helpers**: Easy JWT and API key testing
- **Comprehensive fixtures**: Pre-built test data for common scenarios

### Coverage

Generate coverage reports:
```bash
make test-coverage        # Terminal report
make test-coverage-html   # HTML report in htmlcov/
```

For detailed testing documentation, see `core/tests/README.md`.