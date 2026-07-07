"""Activity statistics served to DDTM members about the collectivity groups of their
department (see the statistics.ddtm_activity views).

Definitions:
- "connection": one AnalyticLog USER_ACCESS row — written on every authenticated app
  load (GET /api/users/me), the only per-event login signal the system records.
- "operational action": one control-status transition on a detection object. Sourced
  from the DetectionData history table and deduped per (object, new status) — see
  _actions_count_by_user.
Stats cover non-staff users that do not belong to any DDTM group.

Read paths share the same cheap scoping helpers; only the paths that need per-user
status run the expensive control-status history scan:
- get_summary: department name + group/active-group counts + (uuid, name) list for the
  section-2 select. Connections only.
- get_user_group_rows: the per-group table rows (counts only, no nested users).
- get_user_group_users: one group's per-user detail rows for the group-detail table.
- get_user_group_monthly_activity: the 12-month breakdown for one group's chart.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from django.db import connection
from django.db.models import Count, Min
from django.db.models.functions import TruncMonth
from django.utils import timezone

from core.constants.statistics import (
    DDTM_ACTIVITY_MONTHS_COUNT,
    DDTM_ACTIVITY_PILOT_MIN_ACTIONS,
    DDTM_ACTIVITY_WINDOW_DAYS,
)
from core.models.analytic_log import AnalyticLog, AnalyticLogType
from core.models.detection import Detection
from core.models.detection_data import DetectionData
from core.models.geo_commune import GeoCommune
from core.models.geo_department import GeoDepartment
from core.models.user import User
from core.models.user_group import UserGroup, UserGroupType, UserUserGroup

DAYS_PER_WEEK = 7

USER_ACTIVITY_STATUS_PILOT = "PILOT"
USER_ACTIVITY_STATUS_ACTIVE = "ACTIVE"
USER_ACTIVITY_STATUS_INACTIVE = "INACTIVE"

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
            rows.append(
                {
                    "uuid": group.uuid,
                    "name": group.name,
                    "users_count": len(member_ids),
                    "active_users_count": sum(
                        1
                        for user_id in member_ids
                        if users_data[user_id]["activity_status"]
                        == USER_ACTIVITY_STATUS_ACTIVE
                    ),
                    "pilot_users_count": sum(
                        1
                        for user_id in member_ids
                        if users_data[user_id]["activity_status"]
                        == USER_ACTIVITY_STATUS_PILOT
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
        """One group's per-user rows, ordered by operational actions desc, then
        connections desc, then email. None if the group is not in the DDTM's scope."""
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
    def get_user_group_monthly_activity(user, user_group_uuid) -> Optional[dict]:
        """The group's charts over the last DDTM_ACTIVITY_MONTHS_COUNT months:
        - months: per bucket each member is counted once — pilot (>= 1 operational
          action that month), else active (>= 1 connection), else inactive.
        - control_status_changes_by_month: control-status transitions split by the new
          status (deduped per object+status+month).
        - report_downloads_by_month / connections_by_month: AnalyticLog counts.
        All series cover the same non-staff, non-DDTM members."""
        group = DdtmActivityService._get_scoped_group(user, user_group_uuid)
        if group is None:
            return None

        month_keys = DdtmActivityService._get_month_keys()
        since = timezone.make_aware(
            datetime(int(month_keys[0][:4]), int(month_keys[0][5:]), 1)
        )

        members_by_group, _ = DdtmActivityService._get_memberships([group])
        member_ids = members_by_group.get(group.id, [])

        transitions = DdtmActivityService._control_status_transitions(member_ids, since)

        connected_months = set()
        if member_ids:
            for user_id, month in (
                AnalyticLog.objects.filter(
                    analytic_log_type=AnalyticLogType.USER_ACCESS,
                    user_id__in=member_ids,
                    created_at__gte=since,
                )
                .annotate(month=TruncMonth("created_at"))
                .values_list("user_id", "month")
                .distinct()
            ):
                connected_months.add(
                    (user_id, timezone.localtime(month).strftime("%Y-%m"))
                )

        acted_months = {
            (user_id, timezone.localtime(history_date).strftime("%Y-%m"))
            for user_id, _, _, history_date in transitions
        }

        months = []
        for month_key in month_keys:
            pilots = {
                user_id
                for user_id in member_ids
                if (user_id, month_key) in acted_months
            }
            actives = {
                user_id
                for user_id in member_ids
                if (user_id, month_key) in connected_months
            } - pilots
            months.append(
                {
                    "month": month_key,
                    "pilot_users_count": len(pilots),
                    "active_users_count": len(actives),
                    "inactive_users_count": len(member_ids)
                    - len(pilots)
                    - len(actives),
                }
            )

        return {
            "uuid": group.uuid,
            "name": group.name,
            "months": months,
            "control_status_changes_by_month": (
                DdtmActivityService._control_status_changes_by_month(
                    transitions, month_keys
                )
            ),
            "report_downloads_by_month": (
                DdtmActivityService._analytic_logs_count_by_month(
                    member_ids, AnalyticLogType.REPORT_DOWNLOAD, since, month_keys
                )
            ),
            "connections_by_month": (
                DdtmActivityService._analytic_logs_count_by_month(
                    member_ids, AnalyticLogType.USER_ACCESS, since, month_keys
                )
            ),
        }

    # ------------------------------------------------------------------- scoping

    @staticmethod
    def _window_start():
        return timezone.now() - timedelta(days=DDTM_ACTIVITY_WINDOW_DAYS)

    @staticmethod
    def _classify_status(actions_count: int, connections_count: int) -> str:
        if actions_count >= DDTM_ACTIVITY_PILOT_MIN_ACTIONS:
            return USER_ACTIVITY_STATUS_PILOT
        if connections_count > 0:
            return USER_ACTIVITY_STATUS_ACTIVE
        return USER_ACTIVITY_STATUS_INACTIVE

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
        """Per-user activity dict keyed by user id, for the members in users_info."""
        user_ids = list(users_info.keys())
        connections = DdtmActivityService._connections_count_by_user(user_ids, since)
        actions = DdtmActivityService._actions_count_by_user(user_ids, since)
        return {
            user_id: {
                "uuid": info["uuid"],
                "email": info["email"],
                "operational_actions_count": actions.get(user_id, 0),
                "connections_count": connections.get(user_id, 0),
                "activity_status": DdtmActivityService._classify_status(
                    actions.get(user_id, 0), connections.get(user_id, 0)
                ),
            }
            for user_id, info in users_info.items()
        }

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

    # --------------------------------------------------------------- monthly series

    @staticmethod
    def _control_status_changes_by_month(transitions, month_keys) -> List[dict]:
        """Per month, the count of control-status changes for each new status, deduped
        per (detection object, new status, month) so a bulk write counts once."""
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

        return [
            {
                "month": month,
                "counts": [
                    {"status": status, "count": count}
                    for status, count in sorted(counts[month].items())
                ],
            }
            for month in month_keys
        ]

    @staticmethod
    def _analytic_logs_count_by_month(
        member_ids, log_type, since, month_keys
    ) -> List[dict]:
        counts = defaultdict(int)
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
                counts[month] += row["count"]
        return [{"month": month, "count": counts.get(month, 0)} for month in month_keys]

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
    def _actions_count_by_user(user_ids: List[int], since) -> Dict[int, int]:
        """Control-status transitions deduped per (detection object, new status): a
        prior letter or multi-edit writes one history row per detection of an object
        and must count as one action, not N."""
        transitions = DdtmActivityService._control_status_transitions(user_ids, since)
        object_key_by_detection_data = (
            DdtmActivityService._object_key_by_detection_data(transitions)
        )

        counts = defaultdict(int)
        seen = set()
        for user_id, detection_data_id, status, _history_date in transitions:
            key = (user_id, object_key_by_detection_data[detection_data_id], status)
            if key in seen:
                continue
            seen.add(key)
            counts[user_id] += 1
        return counts

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

    @staticmethod
    def _get_month_keys() -> List[str]:
        """The last DDTM_ACTIVITY_MONTHS_COUNT month keys ("YYYY-MM"), oldest first,
        current month included."""
        now = timezone.localtime()
        year, month = now.year, now.month
        keys = []
        for _ in range(DDTM_ACTIVITY_MONTHS_COUNT):
            keys.append(f"{year:04d}-{month:02d}")
            month -= 1
            if month == 0:
                year, month = year - 1, 12
        keys.reverse()
        return keys
