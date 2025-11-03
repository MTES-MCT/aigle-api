"""
User and authentication test fixtures.

This module provides functions to create users with different roles,
user groups, and API keys for testing.
"""

from core.models import User, UserRole, UserGroup, UserUserGroup
from rest_framework_api_key.models import APIKey


def create_user(
    email="test@example.com",
    password="testpass123",
    user_role=UserRole.REGULAR,
    **kwargs,
):
    """
    Create a user for testing.

    Args:
        email: User email
        password: User password (will be hashed)
        user_role: User role (SUPER_ADMIN, ADMIN, REGULAR, DEACTIVATED)
        **kwargs: Additional user fields

    Returns:
        User object
    """
    # Check if user already exists
    try:
        user = User.objects.get(email=email)
        return user
    except User.DoesNotExist:
        pass

    user_data = {"email": email, "user_role": user_role, "is_active": True, **kwargs}

    user = User.objects.create_user(password=password, **user_data)
    return user


def create_super_admin(email="admin@example.com", password="adminpass123"):
    """
    Create a super admin user.

    Args:
        email: Admin email
        password: Admin password

    Returns:
        User object with SUPER_ADMIN role
    """
    return create_user(
        email=email,
        password=password,
        user_role=UserRole.SUPER_ADMIN,
        is_staff=True,
        is_superuser=True,
    )


def create_admin(email="admin@example.com", password="adminpass123"):
    """
    Create an admin user.

    Args:
        email: Admin email
        password: Admin password

    Returns:
        User object with ADMIN role
    """
    return create_user(email=email, password=password, user_role=UserRole.ADMIN)


def create_regular_user(email="user@example.com", password="userpass123"):
    """
    Create a regular user.

    Args:
        email: User email
        password: User password

    Returns:
        User object with REGULAR role
    """
    return create_user(email=email, password=password, user_role=UserRole.REGULAR)


def create_deactivated_user(email="deactivated@example.com", password="pass123"):
    """
    Create a deactivated user.

    Args:
        email: User email
        password: User password

    Returns:
        User object with DEACTIVATED role
    """
    return create_user(
        email=email, password=password, user_role=UserRole.DEACTIVATED, is_active=False
    )


def create_user_group(name="Test Group", geo_zones=None):
    """
    Create a user group.

    Args:
        name: Group name
        geo_zones: List of GeoZone objects to associate with group

    Returns:
        UserGroup object
    """
    group, _ = UserGroup.objects.get_or_create(name=name)

    if geo_zones:
        for zone in geo_zones:
            group.geo_zones.add(zone)

    return group


def add_user_to_group(user, user_group):
    """
    Add a user to a user group.

    Args:
        user: User object
        user_group: UserGroup object

    Returns:
        UserUserGroup object
    """
    user_user_group, _ = UserUserGroup.objects.get_or_create(
        user=user, user_group=user_group
    )
    return user_user_group


def create_user_with_group(
    email="grouped@example.com",
    password="pass123",
    user_role=UserRole.REGULAR,
    group_name="Test Group",
    geo_zones=None,
):
    """
    Create a user and associate with a new group.

    Args:
        email: User email
        password: User password
        user_role: User role
        group_name: Name for the new group
        geo_zones: List of GeoZone objects for the group

    Returns:
        tuple: (User, UserGroup, UserUserGroup)
    """
    user = create_user(email=email, password=password, user_role=user_role)
    group = create_user_group(name=group_name, geo_zones=geo_zones)
    user_user_group = add_user_to_group(user, group)

    return user, group, user_user_group


def create_api_key(name="Test API Key"):
    """
    Create an API key for external API testing.

    Args:
        name: API key name

    Returns:
        tuple: (APIKey object, plain text key)
    """
    api_key, key = APIKey.objects.create_key(name=name)
    return api_key, key


def create_test_users_set():
    """
    Create a complete set of test users with different roles.

    Returns:
        dict: Dictionary containing users:
            - super_admin: Super admin user
            - admin: Admin user
            - regular: Regular user
            - deactivated: Deactivated user
    """
    return {
        "super_admin": create_super_admin(email="superadmin@test.com"),
        "admin": create_admin(email="admin@test.com"),
        "regular": create_regular_user(email="regular@test.com"),
        "deactivated": create_deactivated_user(email="deactivated@test.com"),
    }
