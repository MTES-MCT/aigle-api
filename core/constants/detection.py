from core.models.detection_data import DetectionControlStatus

PERCENTAGE_SAME_DETECTION_THRESHOLD = 0.5

# Control statuses meaning a user has acted on a detection (everything except
# NOT_CONTROLLED). Derived from the enum so a newly added status is covered
# automatically and can't silently bypass user-control guards.
CONTROLLED_DETECTION_STATUSES = [
    status
    for status in DetectionControlStatus.values
    if status != DetectionControlStatus.NOT_CONTROLLED
]
