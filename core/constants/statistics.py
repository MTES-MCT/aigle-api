# DDTM activity dashboard thresholds.

from django.db import models

# Window (days) over which connections and operational actions are counted for the
# section-1 overview and the per-user detail table.
DDTM_ACTIVITY_WINDOW_DAYS = 30

# Activity tiers, by operational-action count over the period (fixed thresholds, not
# averaged by period length). See DdtmActivityService._classify_tier.
DDTM_ACTIVITY_PILOT_MIN_ACTIONS = 7  # operational actions -> "pilot"
DDTM_ACTIVITY_RECURRENT_MIN_ACTIONS = 4  # operational actions -> "recurrent"


class DdtmActivityGranularity(models.TextChoices):
    MONTH = "MONTH", "MONTH"
    QUARTER = "QUARTER", "QUARTER"
    SEMESTER = "SEMESTER", "SEMESTER"


# Calendar months per period, and how many periods the charts show, per granularity.
DDTM_ACTIVITY_MONTHS_PER_PERIOD = {
    DdtmActivityGranularity.MONTH: 1,
    DdtmActivityGranularity.QUARTER: 3,
    DdtmActivityGranularity.SEMESTER: 6,
}
DDTM_ACTIVITY_PERIOD_COUNT = {
    DdtmActivityGranularity.MONTH: 12,
    DdtmActivityGranularity.QUARTER: 8,
    DdtmActivityGranularity.SEMESTER: 6,
}
