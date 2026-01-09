from dataclasses import dataclass
from datetime import date, datetime
from typing import (
    Dict,
    Iterable,
    List,
    Literal,
    Optional,
    TypedDict,
    Union,
    cast,
    get_args,
    get_type_hints,
    overload,
)
import mysql.connector
import os

from core.utils.code import find_missing_variables

LuccaAnalyticsTableName = Literal["stats_history", "stats_logs", "stats_users"]
lucca_analytics_table_names = list(get_args(LuccaAnalyticsTableName))


class LuccaAnalyticsTable(TypedDict):
    id: int


class LuccaStatHistory(LuccaAnalyticsTable):
    dossier_id: int
    adherent_id: int
    action_date: datetime
    action_type: str
    ville: str
    interco: str
    departement: str


class LuccaStatLog(LuccaAnalyticsTable):
    utilisateur_id: int
    connexion_date: datetime


class LuccaStatUser(LuccaAnalyticsTable):
    adherent_id: str
    departement: str
    appartenance: str
    nom_appartenance: str
    niveau_acces: str
    utilisateur_id: str


LUCCA_ANALYTICS_TABLE_NAMES_COLUMNS_MAP: Dict[LuccaAnalyticsTableName, List[str]] = {
    "stats_history": [field for field, _ in get_type_hints(LuccaStatHistory).items()],
    "stats_logs": [field for field, _ in get_type_hints(LuccaStatLog).items()],
    "stats_users": [field for field, _ in get_type_hints(LuccaStatUser).items()],
}

LUCCA_ANALYTICS_TABLE_NAMES_TABLES_MAP: Dict[
    LuccaAnalyticsTableName, type[LuccaAnalyticsTable]
] = {
    "stats_history": LuccaStatHistory,
    "stats_logs": LuccaStatLog,
    "stats_users": LuccaStatUser,
}


type RowValue = Union[str, int, datetime, date]


@dataclass
class RowFilter:
    field: str
    value: RowValue
    operator: Literal["=", ">", ">=", "<", "<="] = "="


@dataclass
class OrderBy:
    field: str
    order: Literal["ASC", "DESC"] = "ASC"


class LuccaAnalyticsDatabaseConnector:
    def __init__(self):
        LUCCA_ANALYTICS_SQL_HOST = os.environ.get("LUCCA_ANALYTICS_SQL_HOST")
        LUCCA_ANALYTICS_SQL_DATABASE = os.environ.get("LUCCA_ANALYTICS_SQL_DATABASE")
        LUCCA_ANALYTICS_SQL_USER = os.environ.get("LUCCA_ANALYTICS_SQL_USER")
        LUCCA_ANALYTICS_SQL_PASSWORD = os.environ.get("LUCCA_ANALYTICS_SQL_PASSWORD")
        LUCCA_ANALYTICS_SQL_PORT = os.environ.get("LUCCA_ANALYTICS_SQL_PORT")

        find_missing_variables(
            error_prefix="Cannot connect to distant Lucca database - missing env vars",
            **{
                "LUCCA_ANALYTICS_SQL_HOST": LUCCA_ANALYTICS_SQL_HOST,
                "LUCCA_ANALYTICS_SQL_DATABASE": LUCCA_ANALYTICS_SQL_DATABASE,
                "LUCCA_ANALYTICS_SQL_USER": LUCCA_ANALYTICS_SQL_USER,
                "LUCCA_ANALYTICS_SQL_PASSWORD": LUCCA_ANALYTICS_SQL_PASSWORD,
                "LUCCA_ANALYTICS_SQL_PORT": LUCCA_ANALYTICS_SQL_PORT,
            },
        )

        self.connection = mysql.connector.connect(
            host=LUCCA_ANALYTICS_SQL_HOST,
            database=LUCCA_ANALYTICS_SQL_DATABASE,
            user=LUCCA_ANALYTICS_SQL_USER,
            password=LUCCA_ANALYTICS_SQL_PASSWORD,
            port=LUCCA_ANALYTICS_SQL_PORT,
            ssl_disabled=False,
            ssl_verify_cert=False,
        )

        self.cursor = self.connection.cursor(buffered=True)

    def test_connection(self):
        # test connection
        self.cursor.execute("SELECT VERSION();")

        db_version = self.cursor.fetchone()

        if not db_version:
            raise ValueError("Error connecting to Lucca Analytics distant database")

    @overload
    def get_rows(
        self,
        table_name: Literal["stats_history"],
        filters: Optional[List[RowFilter]] = None,
        order_bys: Optional[List[OrderBy]] = None,
    ) -> Iterable[LuccaStatHistory]: ...

    @overload
    def get_rows(
        self,
        table_name: Literal["stats_logs"],
        filters: Optional[List[RowFilter]] = None,
        order_bys: Optional[List[OrderBy]] = None,
    ) -> Iterable[LuccaStatLog]: ...

    @overload
    def get_rows(
        self,
        table_name: Literal["stats_users"],
        filters: Optional[List[RowFilter]] = None,
        order_bys: Optional[List[OrderBy]] = None,
    ) -> Iterable[LuccaStatUser]: ...

    def get_rows(
        self,
        table_name: LuccaAnalyticsTableName,
        filters: Optional[List[RowFilter]] = None,
        order_bys: Optional[List[OrderBy]] = None,
    ) -> Iterable[LuccaAnalyticsTable]:
        self.cursor.execute(f"SELECT count(*) FROM {table_name}")

        count_res = self.cursor.fetchone()

        if not count_res:
            raise ValueError(f"Cannot fetch count from {table_name}")

        # Type ignore: fetchone returns tuple which is accessed by index
        self.total = int(count_res[0]) if count_res[0] else 0  # type: ignore[index]

        table_columns = [
            col for col in LUCCA_ANALYTICS_TABLE_NAMES_COLUMNS_MAP[table_name]
        ]

        self.cursor.execute(
            f"SELECT {', '.join(table_columns)} FROM {table_name} {_generate_sql_filter(
                filters=filters
            )} {
                _generate_sql_order_by(order_bys=order_bys)
            }"
        )

        def row_to_dict(row) -> LuccaAnalyticsTable:
            return cast(LuccaAnalyticsTable, dict(zip(table_columns, row)))

        # Type ignore for mysql.connector cursor iteration compatibility
        return map(row_to_dict, self.cursor)  # type: ignore[arg-type]

    def close_connection(self):
        if self.cursor:
            self.cursor.close()

        if self.connection:
            self.connection.close()


# utils


def _generate_sql_filter(filters: Optional[List[RowFilter]] = None) -> str:
    if not filters:
        return ""

    return f" WHERE {' AND '.join([f'{filter.field} {filter.operator} {_generate_sql_value(filter.value)}' for filter in filters])}"


def _generate_sql_value(value: RowValue) -> str:
    if isinstance(value, str) or isinstance(value, int):
        return str(value)

    if isinstance(value, date):
        return f"'{value.strftime('%Y-%m-%d')}'"

    if isinstance(value, datetime):
        return f"'{value.strftime('%Y-%m-%d %H:%M:%S')}'"


def _generate_sql_order_by(order_bys: Optional[List[OrderBy]] = None) -> str:
    if not order_bys:
        order_bys = [OrderBy(field="id", order="ASC")]

    return f" ORDER BY {', '.join([f'{order_by.field} {order_by.order}' for order_by in order_bys])}"
