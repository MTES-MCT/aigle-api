from typing import Dict, Optional
from core.models.analytic_log import AnalyticLog, AnalyticLogType
from core.models.user import User


def create_log(
    user: User, analytic_log_type: AnalyticLogType, data: Optional[Dict] = None
):
    AnalyticLog.objects.create(
        user=user,
        analytic_log_type=analytic_log_type,
        data=data,
    )
