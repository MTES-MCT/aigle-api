import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the cache around every test.

    The test DB is rolled back per test, but the cache backend (LocMemCache) is
    not — cached counts, geometries, and version counters would otherwise leak
    between tests and make them order-dependent.
    """
    cache.clear()
    yield
    cache.clear()
