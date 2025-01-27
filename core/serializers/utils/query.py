from typing import List, Optional

from django.db.models import Q

from rest_framework import serializers
from django.db import models


def get_objects(uuids: Optional[List[str]], model: models.Model):
    if uuids is None:
        return None

    # remove potential duplicates
    uuids = list(set(uuids))
    objects = model.objects.filter(uuid__in=uuids).all()

    if len(uuids) != len(objects):
        uuids_not_found = list(set(uuids) - set([object_.uuid for object_ in objects]))

        raise serializers.ValidationError(
            f"Some objects (type: {model.__name__}) were not found, uuids: {
                ", ".join(uuids_not_found)}"
        )

    return objects


def prefix_q(q_expression: Q, prefix: str):
    if not isinstance(q_expression, Q):
        raise ValueError("The provided expression must be a Q object")

    new_q = Q()
    new_q.connector = q_expression.connector

    for child in q_expression.children:
        if isinstance(child, Q):
            prefixed_child = prefix_q(child, prefix)
            new_q.add(prefixed_child, q_expression.connector)
        elif isinstance(child, tuple):
            field, value = child
            prefixed_field = f"{prefix}__{field}"
            new_q.children.append((prefixed_field, value))
        else:
            raise ValueError(f"Unexpected Q child type: {type(child)}")

    return new_q
