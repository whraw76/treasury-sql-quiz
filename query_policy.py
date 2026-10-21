"""A deliberately small SQL vocabulary for a SELECT-only teaching playground."""

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel, ParseError, UnsupportedError

MAX_ROWS = 200
MAX_SQL_LENGTH = 8000

# This is an allowlist of syntax, not a blacklist of dangerous keywords.
# The database login has independent read-only privileges as a second boundary.
ALLOWED_NODES = {
    "Select", "From", "Table", "Identifier", "Column", "Star", "Alias",
    "TableAlias", "Where", "Order", "Ordered", "Group", "Having", "Join",
    "Limit", "Offset", "Literal", "Neg", "And", "Or", "Not", "Paren",
    "EQ", "NEQ", "GT", "GTE", "LT", "LTE", "Between", "In", "Is",
    "Null", "Boolean", "Add", "Sub", "Mul", "Div", "Mod", "Distinct",
    "Count", "Avg", "Sum", "Min", "Max", "Round", "Abs", "Coalesce",
    "Nullif", "Case", "If", "Like", "ILike", "Subquery", "With", "CTE",
    "Cast", "DataType",
}


class QueryError(ValueError):
    """A safe, student-facing query error."""


def prepare_query(sql_text):
    if not isinstance(sql_text, str) or not sql_text.strip():
        raise QueryError("Write a SELECT query first.")
    if len(sql_text) > MAX_SQL_LENGTH:
        raise QueryError("Keep the query under 8,000 characters.")
    try:
        # Parse SQL into a syntax tree so checks examine its structure.
        statements = [s for s in sqlglot.parse(sql_text, read="postgres") if s]
    except (ParseError, RecursionError) as exc:
        raise QueryError("The SQL could not be parsed. Check its syntax.") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise QueryError("Run one SELECT statement at a time.")
    tree = statements[0]
    nodes = list(tree.walk())
    if len(nodes) > 500:
        raise QueryError("This query is too complex for the small practice dataset.")
    if any(type(node).__name__ not in ALLOWED_NODES for node in nodes):
        raise QueryError("Use SELECT, filters, joins, grouping and basic aggregates only.")
    # PostgreSQL DATE literals parse as casts. Other types remain out of scope.
    for data_type in tree.find_all(exp.DataType):
        if data_type.this != exp.DataType.Type.DATE:
            raise QueryError("This quiz supports DATE casts only.")
    cte_names = {cte.alias for cte in tree.find_all(exp.CTE)}
    if cte_names & {"yields", "maturities"}:
        raise QueryError("CTE names must differ from the two dataset table names.")
    for table in tree.find_all(exp.Table):
        if table.catalog or table.db not in ("", "quiz_data"):
            raise QueryError("Only the quiz_data tables are available.")
        if table.name in cte_names and not table.db:
            continue
        if table.name not in {"yields", "maturities"}:
            raise QueryError("Use the yields and maturities tables shown in the schema.")
        # Resolve allowed dataset tables explicitly to the quiz_data schema.
        table.set("db", exp.to_identifier("quiz_data"))
    for limit in tree.find_all(exp.Limit):
        value = limit.expression
        if not isinstance(value, exp.Literal) or value.is_string or not value.this.isdigit():
            raise QueryError("LIMIT must be a nonnegative whole number.")
    for offset in tree.find_all(exp.Offset):
        value = offset.expression
        if not isinstance(value, exp.Literal) or value.is_string or not value.this.isdigit():
            raise QueryError("OFFSET must be a nonnegative whole number.")
    # Keep one extra row so QueryRunner can flag a truncated result.
    limit = tree.args.get("limit")
    if limit is None or int(limit.expression.this) > MAX_ROWS + 1:
        tree = tree.limit(MAX_ROWS + 1)
    try:
        return tree.sql(dialect="postgres", unsupported_level=ErrorLevel.RAISE)
    except UnsupportedError as exc:
        raise QueryError("This SQL feature is not supported in this quiz.") from exc
