from django.db import models

from core.models.detection_data import DetectionControlStatus, DetectionValidationStatus
from core.models.tile_set import TileSetStatus, TileSetType

# Written as `history_change_reason` on the detection data rows the plan switches, so the
# activity statistics can tell them from an agent's own edits.
CONTROL_PLAN_HISTORY_CHANGE_REASON = "CONTROL_PLAN"

# « Aucun PV sur la parcelle »: an official report and what follows it.
OFFICIAL_REPORT_CONTROL_STATUSES = [
    DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP,
    DetectionControlStatus.ADMINISTRATIVE_CONSTRAINT,
    DetectionControlStatus.JUGEMENT,
]

# The control went on: the object left « À contrôler » forward.
CONTROLLED_STATUSES = [
    DetectionControlStatus.CONTROLLED_FIELD,
    DetectionControlStatus.PRIOR_LETTER_SENT,
    DetectionControlStatus.OFFICIAL_REPORT_DRAWN_UP,
    DetectionControlStatus.ADMINISTRATIVE_CONSTRAINT,
    DetectionControlStatus.JUGEMENT,
    DetectionControlStatus.OBSERVARTION_REPORT_REDACTED,
    DetectionControlStatus.REHABILITATED,
]

# An object found legal or a false detection needs no control any more.
CLOSED_VALIDATION_STATUSES = [
    DetectionValidationStatus.LEGITIMATE,
    DetectionValidationStatus.INVALIDATED,
]

SELECTABLE_VALIDATION_STATUSES = [
    DetectionValidationStatus.DETECTED_NOT_VERIFIED,
    DetectionValidationStatus.SUSPECT,
]

# Tile sets that hold the « current » detection of an object (the most recent one).
CURRENT_DETECTION_TILE_SET_TYPES = [TileSetType.BACKGROUND, TileSetType.PARTIAL]
EXCLUDED_TILE_SET_STATUSES = [TileSetStatus.DEACTIVATED]

DEFAULT_SCORE_MIN = 0.3
MAX_PARCELS_COUNT = 5000
# Beyond the parcels asked for, this many more are stored as a waiting list (at least as
# many as asked): excluding a proposed parcel brings the next one in.
MIN_WAITING_LIST_SIZE = 500
PROPOSAL_STATEMENT_TIMEOUT_MS = 20000


class ControlPlanRankingCriterion(models.TextChoices):
    OBJECTS_COUNT = "OBJECTS_COUNT", "OBJECTS_COUNT"
    NEW_OBJECTS_COUNT = "NEW_OBJECTS_COUNT", "NEW_OBJECTS_COUNT"
    OBJECT_TYPE_PRIORITY = "OBJECT_TYPE_PRIORITY", "OBJECT_TYPE_PRIORITY"
    SMALL_PARCELS = "SMALL_PARCELS", "SMALL_PARCELS"


DEFAULT_RANKING_CRITERIA = [
    ControlPlanRankingCriterion.OBJECTS_COUNT,
    ControlPlanRankingCriterion.NEW_OBJECTS_COUNT,
]

# « Petites parcelles » ranks by size class (m², upper bounds), not by the exact area: two
# parcels rarely share one, so an exact area would leave nothing for the next criteria.
PARCEL_AREA_CLASSES = [1000, 2500, 5000, 10000]


class ControlPlanFollowUpStatus(models.TextChoices):
    TO_CONTROL = "TO_CONTROL", "TO_CONTROL"
    CONTROLLED = "CONTROLLED", "CONTROLLED"
    RELEASED = "RELEASED", "RELEASED"


class ControlPlanParcelSection(models.TextChoices):
    PROPOSED = "PROPOSED", "PROPOSED"
    WAITING = "WAITING", "WAITING"
    EXCLUDED = "EXCLUDED", "EXCLUDED"
    PLANNED = "PLANNED", "PLANNED"
    REMOVED = "REMOVED", "REMOVED"
