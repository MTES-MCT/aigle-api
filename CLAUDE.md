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
source .env && source venv/bin/activate && make start
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

### Development Server
```bash
# Start local development server
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
- Authentication via JWT tokens using djoser
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