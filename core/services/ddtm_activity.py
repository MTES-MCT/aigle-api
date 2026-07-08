"""Activity statistics served to DDTM members about the collectivity groups of their
department (see the statistics.ddtm_activity views).

Definitions:
- "connection": one AnalyticLog USER_ACCESS row — written on every authenticated app
  load (GET /api/users/me), the only per-event login signal the system records.
- "operational action": one control-status transition on a detection object. Sourced
  from the DetectionData history table and deduped per (object, new status).
Stats cover non-staff users that do not belong to any DDTM group.

Activity tiers (mutually exclusive, most to least engaged), evaluated over a period for
one entity (a user, or a group = the aggregate of its members):
- pilot     : operational actions >= 7
- recurrent : operational actions >= 4
- active    : at least 1 operational action OR 1 connection
- inactive  : no action and no connection
Thresholds are fixed (not scaled by period length).

Read paths:
- get_summary / get_user_group_rows: section-1 overview (30-day window, legacy 3-tier).
- get_user_group_users: one group's per-user detail rows (30-day window, 4 tiers).
- get_user_group_activity: one group's charts, per-user tiers, at the chosen granularity.
- get_groups_activity: department-wide chart, per-group tiers, at the chosen granularity.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from django.db import connection
from django.db.models import Count, Min
from django.db.models.functions import TruncMonth
from django.utils import timezone

from core.constants.statistics import (
    DDTM_ACTIVITY_MONTHS_PER_PERIOD,
    DDTM_ACTIVITY_PERIOD_COUNT,
    DDTM_ACTIVITY_PILOT_MIN_ACTIONS,
    DDTM_ACTIVITY_RECURRENT_MIN_ACTIONS,
    DDTM_ACTIVITY_WINDOW_DAYS,
    DdtmActivityGranularity,
)
from core.models.analytic_log import AnalyticLog, AnalyticLogType
from core.models.detection import Detection
from core.models.detection_data import DetectionData
from core.models.geo_commune import GeoCommune
from core.models.geo_department import GeoDepartment
from core.models.user import User
from core.models.user_group import UserGroup, UserGroupType, UserUserGroup

DAYS_PER_WEEK = 7

ACTIVITY_TIER_PILOT = "PILOT"
ACTIVITY_TIER_RECURRENT = "RECURRENT"
ACTIVITY_TIER_ACTIVE = "ACTIVE"
ACTIVITY_TIER_INACTIVE = "INACTIVE"

_HISTORY_TABLE = DetectionData.history.model._meta.db_table

# One row per real control-status transition: the status differs from the previous
# history row of the same detection data (LAG over the full history, so a predecessor
# outside the window still counts as the "before" value). We cannot rely on
# changed_fields: bulk writes (multi-edit, prior letter) skip the
# pre_create_historical_record signal and leave it NULL. No-op saves and creations
# ('+' rows have no predecessor) are excluded.
_CONTROL_STATUS_TRANSITIONS_SQL = f"""
    WITH relevant_ids AS (
        SELECT DISTINCT id
        FROM {_HISTORY_TABLE}
        WHERE history_date >= %(since)s AND history_user_id = ANY(%(user_ids)s)
    ),
    ordered AS (
        SELECT h.id,
               h.history_user_id,
               h.history_date,
               h.detection_control_status,
               LAG(h.detection_control_status) OVER (
                   PARTITION BY h.id
                   ORDER BY h.history_date, h.history_id
               ) AS previous_control_status
        FROM {_HISTORY_TABLE} h
        INNER JOIN relevant_ids USING (id)
    )
    SELECT history_user_id, id, detection_control_status, history_date
    FROM ordered
    WHERE history_date >= %(since)s
      AND history_user_id = ANY(%(user_ids)s)
      AND previous_control_status IS NOT NULL
      AND previous_control_status <> detection_control_status
"""


class DdtmActivityService:
    # ---------------------------------------------------------------- read paths

    @staticmethod
    def get_summary(user) -> Optional[dict]:
        """Stat tiles + section-2 select options. Connections only (cheap)."""
        department = DdtmActivityService._get_department(user)
        if department is None:
            return None

        since = DdtmActivityService._window_start()
        groups = list(DdtmActivityService._get_scoped_groups(department))
        members_by_group, users_info = DdtmActivityService._get_memberships(groups)
        connections = DdtmActivityService._connections_count_by_user(
            list(users_info.keys()), since
        )

        active_groups_count = sum(
            1
            for group in groups
            if any(
                connections.get(user_id, 0) > 0
                for user_id in members_by_group.get(group.id, [])
            )
        )

        return {
            "department_name": department.name,
            "user_groups_count": len(groups),
            "active_user_groups_count": active_groups_count,
            "user_groups": [
                {"uuid": group.uuid, "name": group.name} for group in groups
            ],
        }

    @staticmethod
    def get_user_group_rows(user) -> Optional[List[dict]]:
        """Per-group table rows (counts only — the per-user detail is a separate call
        so the groups table doesn't ship every member on every load)."""
        department = DdtmActivityService._get_department(user)
        if department is None:
            return None

        since = DdtmActivityService._window_start()
        groups = list(DdtmActivityService._get_scoped_groups(department))
        members_by_group, users_info = DdtmActivityService._get_memberships(groups)
        users_data = DdtmActivityService._build_users_data(users_info, since)
        first_login_by_user = DdtmActivityService._first_login_by_user(
            list(users_info.keys())
        )
        now = timezone.now()

        rows = []
        for group in groups:
            member_ids = members_by_group.get(group.id, [])
            deployment = DdtmActivityService._deployment_datetime(
                member_ids, first_login_by_user
            )
            statuses = [
                DdtmActivityService._classify_tier(
                    users_data[user_id]["operational_actions_count"],
                    users_data[user_id]["connections_count"],
                )
                for user_id in member_ids
            ]
            rows.append(
                {
                    "uuid": group.uuid,
                    "name": group.name,
                    "users_count": len(member_ids),
                    # Active = any tier above inactive (>= 1 action or connection).
                    "active_users_count": sum(
                        1 for status in statuses if status != ACTIVITY_TIER_INACTIVE
                    ),
                    "pilot_users_count": sum(
                        1 for status in statuses if status == ACTIVITY_TIER_PILOT
                    ),
                    "deployment_date": (
                        timezone.localtime(deployment).date() if deployment else None
                    ),
                    "deployed_since_weeks": (
                        (now - deployment).days // DAYS_PER_WEEK if deployment else None
                    ),
                }
            )
        return rows

    @staticmethod
    def get_user_group_users(user, user_group_uuid) -> Optional[List[dict]]:
        """One group's per-user rows (30-day window, 4 tiers), ordered by operational
        actions desc, then connections desc, then email. None if out of the DDTM scope."""
        group = DdtmActivityService._get_scoped_group(user, user_group_uuid)
        if group is None:
            return None

        since = DdtmActivityService._window_start()
        members_by_group, users_info = DdtmActivityService._get_memberships([group])
        users_data = DdtmActivityService._build_users_data(users_info, since)

        members = [
            users_data[user_id] for user_id in members_by_group.get(group.id, [])
        ]
        members.sort(
            key=lambda member: (
                -member["operational_actions_count"],
                -member["connections_count"],
                member["email"],
            )
        )
        return members

    @staticmethod
    def get_user_group_activity(user, user_group_uuid, granularity) -> Optional[dict]:
        """One group's charts at the chosen granularity. Periods before the group's
        deployment are returned empty (all zero) and flagged via no_data_until_period so
        the UI can grey them out.
        - activity_by_period: each member classified into one tier per period, + total.
        - control_status_changes_by_period: transitions split by the new status.
        - report_downloads_by_period / connections_by_period: AnalyticLog counts.
        All series cover the same non-staff, non-DDTM members."""
        group = DdtmActivityService._get_scoped_group(user, user_group_uuid)
        if group is None:
            return None

        members_by_group, _ = DdtmActivityService._get_memberships([group])
        member_ids = members_by_group.get(group.id, [])

        periods = DdtmActivityService._get_periods(granularity)
        since = DdtmActivityService._periods_start(periods)
        ops_by_user_month, transitions = DdtmActivityService._ops_count_by_user_month(
            member_ids, since
        )
        conns_by_user_month = DdtmActivityService._conns_count_by_user_month(
            member_ids, since
        )

        deployment = DdtmActivityService._deployment_datetime(
            member_ids, DdtmActivityService._first_login_by_user(member_ids)
        )
        deployment_period = (
            DdtmActivityService._period_key_of_month(
                timezone.localtime(deployment).strftime("%Y-%m"), granularity
            )
            if deployment
            else None
        )
        pre_deploy_keys = [
            period["key"]
            for period in periods
            if deployment_period is None or period["key"] < deployment_period
        ]

        activity = DdtmActivityService._activity_tiers_by_period(
            [[user_id] for user_id in member_ids],
            periods,
            ops_by_user_month,
            conns_by_user_month,
            empty_period_keys=set(pre_deploy_keys),
        )

        return {
            "uuid": group.uuid,
            "name": group.name,
            "granularity": granularity,
            "deployment_date": (
                timezone.localtime(deployment).date() if deployment else None
            ),
            "no_data_until_period": pre_deploy_keys[-1] if pre_deploy_keys else None,
            "activity_by_period": activity,
            "control_status_changes_by_period": (
                DdtmActivityService._control_status_changes_by_period(
                    transitions, periods
                )
            ),
            "report_downloads_by_period": (
                DdtmActivityService._analytic_logs_by_period(
                    member_ids, AnalyticLogType.REPORT_DOWNLOAD, since, periods
                )
            ),
            "connections_by_period": (
                DdtmActivityService._analytic_logs_by_period(
                    member_ids, AnalyticLogType.USER_ACCESS, since, periods
                )
            ),
        }

    @staticmethod
    def get_groups_activity(user, granularity) -> Optional[dict]:
        """Department-wide chart: each collectivity group classified into one tier per
        period (its members' activity aggregated), + the total group count. None if no
        department is linked to the user's DDTM group."""
        department = DdtmActivityService._get_department(user)
        if department is None:
            return None

        groups = list(DdtmActivityService._get_scoped_groups(department))
        members_by_group, users_info = DdtmActivityService._get_memberships(groups)

        periods = DdtmActivityService._get_periods(granularity)
        since = DdtmActivityService._periods_start(periods)
        ops_by_user_month, _ = DdtmActivityService._ops_count_by_user_month(
            list(users_info.keys()), since
        )
        conns_by_user_month = DdtmActivityService._conns_count_by_user_month(
            list(users_info.keys()), since
        )

        # A group exists (has data) from the earliest creation of one of its members;
        # before that it is not counted, not shown as inactive.
        created_month_by_user = DdtmActivityService._created_month_by_user(
            list(users_info.keys())
        )
        existence_months = [
            DdtmActivityService._earliest_existence_month(
                members_by_group.get(group.id, []), created_month_by_user
            )
            for group in groups
        ]

        activity = DdtmActivityService._activity_tiers_by_period(
            [members_by_group.get(group.id, []) for group in groups],
            periods,
            ops_by_user_month,
            conns_by_user_month,
            existence_months=existence_months,
        )
        return {"granularity": granularity, "activity_by_period": activity}

    # ------------------------------------------------------------------- scoping

    @staticmethod
    def _window_start():
        return timezone.now() - timedelta(days=DDTM_ACTIVITY_WINDOW_DAYS)

    @staticmethod
    def _classify_tier(actions_count: int, connections_count: int) -> str:
        """Tier of one entity over a period from its operational-action and connection
        totals (see the module docstring)."""
        if actions_count >= DDTM_ACTIVITY_PILOT_MIN_ACTIONS:
            return ACTIVITY_TIER_PILOT
        if actions_count >= DDTM_ACTIVITY_RECURRENT_MIN_ACTIONS:
            return ACTIVITY_TIER_RECURRENT
        if actions_count > 0 or connections_count > 0:
            return ACTIVITY_TIER_ACTIVE
        return ACTIVITY_TIER_INACTIVE

    @staticmethod
    def _get_department(user) -> Optional[GeoDepartment]:
        """The department linked (via geo_zones) to the user's DDTM group. DDTM groups
        are expected to carry exactly one department; ordered for determinism."""
        return (
            GeoDepartment.objects.filter(
                user_groups__user_group_type=UserGroupType.DDTM,
                user_groups__user_user_groups__user=user,
            )
            .order_by("name")
            .first()
        )

    @staticmethod
    def _get_scoped_groups(department: GeoDepartment):
        """Groups the dashboard covers: linked to at least one commune of the
        department. DDTM groups are excluded — the stats are about collectivities."""
        commune_ids = GeoCommune.objects.filter(department=department).values_list(
            "id", flat=True
        )
        return (
            UserGroup.objects.filter(geo_zones__id__in=commune_ids)
            .exclude(user_group_type=UserGroupType.DDTM)
            .distinct()
            .order_by("name")
        )

    @staticmethod
    def _get_scoped_group(user, user_group_uuid) -> Optional[UserGroup]:
        department = DdtmActivityService._get_department(user)
        if department is None:
            return None
        return (
            DdtmActivityService._get_scoped_groups(department)
            .filter(uuid=user_group_uuid)
            .first()
        )

    @staticmethod
    def _get_memberships(groups) -> Tuple[Dict[int, List[int]], Dict[int, dict]]:
        """Members covered by the stats: non-staff users not belonging to any DDTM
        group. Returns ({group_id: [user_id]}, {user_id: {"uuid", "email"}})."""
        members_by_group = defaultdict(list)
        users_info = {}
        rows = (
            UserUserGroup.objects.filter(user_group__in=groups, user__is_staff=False)
            .exclude(
                user__user_user_groups__user_group__user_group_type=UserGroupType.DDTM
            )
            .values_list("user_group_id", "user_id", "user__uuid", "user__email")
        )
        for group_id, user_id, uuid, email in rows:
            members_by_group[group_id].append(user_id)
            users_info[user_id] = {"uuid": uuid, "email": email}
        return members_by_group, users_info

    @staticmethod
    def _build_users_data(users_info: Dict[int, dict], since) -> Dict[int, dict]:
        """Per-user activity dict keyed by user id, for the members in users_info. The
        30-day tier (4 tiers) backs the per-user detail badge."""
        user_ids = list(users_info.keys())
        connections = DdtmActivityService._connections_count_by_user(user_ids, since)
        actions = DdtmActivityService._actions_count_by_user(user_ids, since)
        return {
            user_id: {
                "uuid": info["uuid"],
                "email": info["email"],
                "operational_actions_count": actions.get(user_id, 0),
                "connections_count": connections.get(user_id, 0),
                "activity_status": DdtmActivityService._classify_tier(
                    actions.get(user_id, 0), connections.get(user_id, 0)
                ),
            }
            for user_id, info in users_info.items()
        }

    # ------------------------------------------------------------------- periods

    @staticmethod
    def _get_periods(granularity) -> List[dict]:
        """The last DDTM_ACTIVITY_PERIOD_COUNT calendar periods, oldest first, current
        period last. Each is {"key", "month_keys": ["YYYY-MM", ...]}. Quarters and
        semesters are calendar-aligned (Q1 = Jan-Mar, S1 = Jan-Jun)."""
        months_per = DDTM_ACTIVITY_MONTHS_PER_PERIOD[granularity]
        count = DDTM_ACTIVITY_PERIOD_COUNT[granularity]
        periods_per_year = 12 // months_per
        now = timezone.localtime()
        year = now.year
        ordinal = (now.month - 1) // months_per

        periods = []
        for _ in range(count):
            month_start = ordinal * months_per + 1
            periods.append(
                {
                    "key": DdtmActivityService._period_key(year, ordinal, granularity),
                    "month_keys": [
                        f"{year:04d}-{month:02d}"
                        for month in range(month_start, month_start + months_per)
                    ],
                }
            )
            ordinal -= 1
            if ordinal < 0:
                year -= 1
                ordinal = periods_per_year - 1
        periods.reverse()
        return periods

    @staticmethod
    def _period_key(year: int, ordinal: int, granularity) -> str:
        if granularity == DdtmActivityGranularity.MONTH:
            return f"{year:04d}-{ordinal + 1:02d}"
        prefix = "Q" if granularity == DdtmActivityGranularity.QUARTER else "S"
        return f"{year:04d}-{prefix}{ordinal + 1}"

    @staticmethod
    def _period_key_of_month(month_key: str, granularity) -> str:
        year, month = int(month_key[:4]), int(month_key[5:7])
        ordinal = (month - 1) // DDTM_ACTIVITY_MONTHS_PER_PERIOD[granularity]
        return DdtmActivityService._period_key(year, ordinal, granularity)

    @staticmethod
    def _periods_start(periods: List[dict]):
        first_month = periods[0]["month_keys"][0]
        return timezone.make_aware(
            datetime(int(first_month[:4]), int(first_month[5:7]), 1)
        )

    # --------------------------------------------------------------- period series

    @staticmethod
    def _activity_tiers_by_period(
        entities: List[List[int]],
        periods: List[dict],
        ops_by_user_month: Dict[Tuple[int, str], int],
        conns_by_user_month: Dict[Tuple[int, str], int],
        empty_period_keys=frozenset(),
        existence_months: Optional[List[Optional[str]]] = None,
    ) -> List[dict]:
        """For each period, classify every entity (a list of member ids) into one tier
        from its members' aggregated ops/connections, and count entities per tier.
        `empty_period_keys` are returned all-zero (pre-deployment). `existence_months`
        (parallel to entities): an entity is skipped for periods ending before its
        existence month — it has no data yet, rather than counting as inactive."""
        result = []
        for period in periods:
            if period["key"] in empty_period_keys:
                result.append(
                    {
                        "period": period["key"],
                        "pilot_count": 0,
                        "recurrent_count": 0,
                        "active_count": 0,
                        "inactive_count": 0,
                        "total_count": 0,
                    }
                )
                continue
            period_last_month = period["month_keys"][-1]
            tiers = defaultdict(int)
            total = 0
            for index, member_ids in enumerate(entities):
                if existence_months is not None:
                    existence = existence_months[index]
                    if existence is None or existence > period_last_month:
                        continue
                ops = sum(
                    ops_by_user_month.get((user_id, month), 0)
                    for user_id in member_ids
                    for month in period["month_keys"]
                )
                conns = sum(
                    conns_by_user_month.get((user_id, month), 0)
                    for user_id in member_ids
                    for month in period["month_keys"]
                )
                tiers[DdtmActivityService._classify_tier(ops, conns)] += 1
                total += 1
            result.append(
                {
                    "period": period["key"],
                    "pilot_count": tiers[ACTIVITY_TIER_PILOT],
                    "recurrent_count": tiers[ACTIVITY_TIER_RECURRENT],
                    "active_count": tiers[ACTIVITY_TIER_ACTIVE],
                    "inactive_count": tiers[ACTIVITY_TIER_INACTIVE],
                    "total_count": total,
                }
            )
        return result

    @staticmethod
    def _control_status_changes_by_period(transitions, periods) -> List[dict]:
        """Per period, the count of control-status changes for each new status (deduped
        per detection object + new status + month, then summed over the period's months)."""
        counts_by_month = DdtmActivityService._control_status_counts_by_month(
            transitions
        )
        result = []
        for period in periods:
            aggregated = defaultdict(int)
            for month in period["month_keys"]:
                for status, count in counts_by_month.get(month, {}).items():
                    aggregated[status] += count
            result.append(
                {
                    "period": period["key"],
                    "counts": [
                        {"status": status, "count": count}
                        for status, count in sorted(aggregated.items())
                    ],
                }
            )
        return result

    @staticmethod
    def _control_status_counts_by_month(transitions) -> Dict[str, Dict[str, int]]:
        object_key_by_detection_data = (
            DdtmActivityService._object_key_by_detection_data(transitions)
        )
        seen = set()
        counts = defaultdict(lambda: defaultdict(int))
        for _user_id, detection_data_id, status, history_date in transitions:
            month = timezone.localtime(history_date).strftime("%Y-%m")
            key = (object_key_by_detection_data[detection_data_id], status, month)
            if key in seen:
                continue
            seen.add(key)
            counts[month][status] += 1
        return counts

    @staticmethod
    def _analytic_logs_by_period(member_ids, log_type, since, periods) -> List[dict]:
        counts_by_month = defaultdict(int)
        if member_ids:
            for row in (
                AnalyticLog.objects.filter(
                    analytic_log_type=log_type,
                    user_id__in=member_ids,
                    created_at__gte=since,
                )
                .annotate(month=TruncMonth("created_at"))
                .values("month")
                .annotate(count=Count("id"))
            ):
                month = timezone.localtime(row["month"]).strftime("%Y-%m")
                counts_by_month[month] += row["count"]
        return [
            {
                "period": period["key"],
                "count": sum(
                    counts_by_month.get(month, 0) for month in period["month_keys"]
                ),
            }
            for period in periods
        ]

    # ----------------------------------------------------------------- deployment

    @staticmethod
    def _first_login_by_user(user_ids: List[int]) -> Dict[int, object]:
        """Each user's earliest recorded last_login, read from the User history table
        (core_user.last_login only keeps the latest). NULLs (never logged in) excluded."""
        if not user_ids:
            return {}
        return {
            row["id"]: row["first_login"]
            for row in User.history.filter(id__in=user_ids, last_login__isnull=False)
            .values("id")
            .annotate(first_login=Min("last_login"))
        }

    @staticmethod
    def _deployment_datetime(member_ids, first_login_by_user):
        """Deployment = the earliest first login across a group's members. None if no
        member has ever logged in."""
        logins = [
            first_login_by_user[user_id]
            for user_id in member_ids
            if user_id in first_login_by_user
        ]
        return min(logins) if logins else None

    @staticmethod
    def _created_month_by_user(user_ids: List[int]) -> Dict[int, str]:
        """{user_id: "YYYY-MM" of account creation}."""
        if not user_ids:
            return {}
        return {
            user_id: timezone.localtime(created_at).strftime("%Y-%m")
            for user_id, created_at in User.objects.filter(id__in=user_ids).values_list(
                "id", "created_at"
            )
        }

    @staticmethod
    def _earliest_existence_month(member_ids, created_month_by_user) -> Optional[str]:
        """Earliest member creation month for a group ("YYYY-MM"), None if it has no
        member (never has data)."""
        months = [
            created_month_by_user[user_id]
            for user_id in member_ids
            if user_id in created_month_by_user
        ]
        return min(months) if months else None

    # ------------------------------------------------------------------- signals

    @staticmethod
    def _connections_count_by_user(user_ids: List[int], since) -> Dict[int, int]:
        if not user_ids:
            return {}
        return {
            row["user_id"]: row["count"]
            for row in AnalyticLog.objects.filter(
                analytic_log_type=AnalyticLogType.USER_ACCESS,
                user_id__in=user_ids,
                created_at__gte=since,
            )
            .values("user_id")
            .annotate(count=Count("id"))
        }

    @staticmethod
    def _conns_count_by_user_month(member_ids, since) -> Dict[Tuple[int, str], int]:
        """{(user_id, "YYYY-MM"): connection count}."""
        counts = defaultdict(int)
        if member_ids:
            for row in (
                AnalyticLog.objects.filter(
                    analytic_log_type=AnalyticLogType.USER_ACCESS,
                    user_id__in=member_ids,
                    created_at__gte=since,
                )
                .annotate(month=TruncMonth("created_at"))
                .values("user_id", "month")
                .annotate(count=Count("id"))
            ):
                month = timezone.localtime(row["month"]).strftime("%Y-%m")
                counts[(row["user_id"], month)] += row["count"]
        return counts

    @staticmethod
    def _actions_count_by_user(user_ids: List[int], since) -> Dict[int, int]:
        """Control-status transitions over the whole window, deduped per (user, detection
        object, new status). Backs the 30-day per-user table."""
        counts_by_user_month, _ = DdtmActivityService._ops_count_by_user_month(
            user_ids, since
        )
        counts = defaultdict(int)
        for (user_id, _month), count in counts_by_user_month.items():
            counts[user_id] += count
        return counts

    @staticmethod
    def _ops_count_by_user_month(
        member_ids, since
    ) -> Tuple[Dict[Tuple[int, str], int], List[Tuple]]:
        """({(user_id, "YYYY-MM"): operational-action count}, raw transitions). Actions
        are deduped per (user, detection object, new status, month) so a bulk write (one
        history row per detection of an object) counts once per month."""
        transitions = DdtmActivityService._control_status_transitions(member_ids, since)
        object_key_by_detection_data = (
            DdtmActivityService._object_key_by_detection_data(transitions)
        )
        counts = defaultdict(int)
        seen = set()
        for user_id, detection_data_id, status, history_date in transitions:
            month = timezone.localtime(history_date).strftime("%Y-%m")
            key = (
                user_id,
                object_key_by_detection_data[detection_data_id],
                status,
                month,
            )
            if key in seen:
                continue
            seen.add(key)
            counts[(user_id, month)] += 1
        return counts, transitions

    @staticmethod
    def _control_status_transitions(user_ids: List[int], since) -> List[Tuple]:
        """Rows (history_user_id, detection_data_id, control_status, history_date)."""
        if not user_ids:
            return []
        with connection.cursor() as cursor:
            cursor.execute(
                _CONTROL_STATUS_TRANSITIONS_SQL,
                {"since": since, "user_ids": list(user_ids)},
            )
            return cursor.fetchall()

    @staticmethod
    def _object_key_by_detection_data(transitions) -> Dict[int, object]:
        """Map each transition's detection_data_id to its detection object id, for
        deduping per object. Orphan detection datas (no Detection row) get a unique
        per-detection-data key so distinct ones are never merged."""
        detection_data_ids = {row[1] for row in transitions}
        object_id_by_detection_data = dict(
            Detection.objects.filter(
                detection_data_id__in=detection_data_ids
            ).values_list("detection_data_id", "detection_object_id")
        )
        return {
            detection_data_id: object_id_by_detection_data.get(
                detection_data_id, f"detection-data-{detection_data_id}"
            )
            for detection_data_id in detection_data_ids
        }
