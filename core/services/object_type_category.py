from typing import List, Dict, Any, Optional
from django.db import transaction
from rest_framework import serializers

from core.models.object_type import ObjectType
from core.models.object_type_category import (
    ObjectTypeCategory,
    ObjectTypeCategoryObjectType,
)


class ObjectTypeCategoryService:
    """Service for handling ObjectTypeCategory business logic."""

    @staticmethod
    def create_object_type_category(
        name: str,
        object_type_category_object_types: Optional[List[Dict[str, Any]]] = None,
    ) -> ObjectTypeCategory:
        """Create object type category with object type relationships."""
        with transaction.atomic():
            instance = ObjectTypeCategory(name=name)
            instance.save()

            if object_type_category_object_types:
                ObjectTypeCategoryService._set_object_type_relationships(
                    instance, object_type_category_object_types
                )

            return instance

    @staticmethod
    def update_object_type_category(
        instance: ObjectTypeCategory,
        name: Optional[str] = None,
        object_type_category_object_types: Optional[List[Dict[str, Any]]] = None,
    ) -> ObjectTypeCategory:
        """Update object type category with object type relationships."""
        with transaction.atomic():
            if name is not None:
                instance.name = name

            if object_type_category_object_types is not None:
                ObjectTypeCategoryService._set_object_type_relationships(
                    instance, object_type_category_object_types
                )

            instance.save()
            return instance

    @staticmethod
    def _set_object_type_relationships(
        object_type_category: ObjectTypeCategory,
        object_type_category_object_types_raw: List[Dict[str, Any]],
    ) -> None:
        """Set object type relationships for category."""
        if not object_type_category_object_types_raw:
            return

        # Validate object types exist
        object_type_uuids_statuses_map = {
            otcot["object_type_uuid"]: otcot["object_type_category_object_type_status"]
            for otcot in object_type_category_object_types_raw
        }
        object_types_uuids = list(object_type_uuids_statuses_map.keys())
        object_types = ObjectType.objects.filter(uuid__in=object_types_uuids)

        if len(object_types_uuids) != len(object_types):
            uuids_not_found = list(
                set(object_types_uuids)
                - set([str(object_type.uuid) for object_type in object_types])
            )
            raise serializers.ValidationError(
                f"Some object types were not found, uuids: {', '.join(uuids_not_found)}"
            )

        # Create new relationships
        object_type_category_object_types = []
        for object_type in object_types:
            object_type_category_object_types.append(
                ObjectTypeCategoryObjectType(
                    object_type_category=object_type_category,
                    object_type=object_type,
                    object_type_category_object_type_status=object_type_uuids_statuses_map[
                        object_type.uuid
                    ],
                )
            )

        # Remove old relationships and create new ones
        previous_relationships = (
            object_type_category.object_type_category_object_types.all()
        )
        previous_relationships.delete()
        ObjectTypeCategoryObjectType.objects.bulk_create(
            object_type_category_object_types
        )
