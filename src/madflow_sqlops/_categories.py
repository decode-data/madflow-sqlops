"""Classify a parsed sqlglot AST against every gdt v0.2 category.

One function per category (`_add_*`), all invoked from a single walk in
`build_operations`. See ../gdt/docs/grammar.md and docs/decisions.md for the
spec this mirrors -- comments below point at the specific ADR/example a
non-obvious choice is grounded in.
"""

from __future__ import annotations

from typing import Any

from sqlglot import exp

from ._allowlists import AI_FUNCTION_NAMES, COLUMN_HASH_FALLBACK_NAMES
from ._ast_utils import alias_output, expression_summary, source_columns

CATEGORY_NAMES: tuple[str, ...] = (
    "join",
    "filter",
    "set_op",
    "rename",
    "compute",
    "aggregate",
    "window",
    "cast",
    "conditional",
    "subquery_cte",
    "wildcard_select",
    "json_parse",
    "json_extract",
    "unnest",
    "ai_function",
    "udf",
    "column_hash",
)

Operations = dict[str, list[dict[str, Any]]]


def build_operations(root: exp.Expression, dialect: str | None) -> Operations:
    ops: Operations = {name: [] for name in CATEGORY_NAMES}

    # Select-scoped categories: these need the enclosing Select's structure
    # (projection list order, the From/Join chain) rather than a bare node
    # type match, so they're handled per-Select rather than in the generic
    # node walk below.
    for select in root.find_all(exp.Select):
        _add_projections(select, dialect, ops)
        _add_joins(select, dialect, ops)
        _add_filter(select, dialect, ops)

    # Generic single walk: every other category is decided purely by node
    # type (plus, for a few, immediate-parent context to avoid double-
    # counting a nested node already covered by its wrapping node -- see the
    # comments at each branch). This is what makes ADR 0002 (compute and the
    # structural-signal categories are independent) fall out for free: a
    # Case/Cast/aggregate/Window nested inside an Alias already tagged
    # `compute` is still visited here and tagged on its own terms.
    for node in root.walk():
        if isinstance(node, exp.Window):
            _add_window(node, dialect, ops)
        elif isinstance(node, exp.Case):
            _add_conditional_case(node, dialect, ops)
        elif isinstance(node, exp.If) and not isinstance(node.parent, exp.Case):
            # exp.If also appears as each WHEN/THEN pair inside exp.Case.ifs;
            # only a *standalone* If (a dialect single-branch IFF/IF() call)
            # gets its own conditional entry here -- the branches nested
            # inside a Case are already carried by that Case's own entry.
            _add_conditional_if(node, dialect, ops)
        elif isinstance(node, exp.Cast):  # exp.TryCast subclasses exp.Cast
            _add_cast(node, dialect, ops)
        elif isinstance(node, exp.ParseJSON):
            _add_json_parse(node, dialect, ops)
        elif isinstance(node, (exp.JSONExtract, exp.JSONExtractScalar)):
            if not isinstance(node.parent, (exp.JSONExtract, exp.JSONExtractScalar)):
                _add_json_extract(node, dialect, ops)
            # else: an inner hop of a chained ->/->> access, folded into the
            # outer entry by _add_json_extract's own descent.
        elif isinstance(node, (exp.MD5, exp.SHA, exp.SHA2, exp.FarmFingerprint)):
            _add_column_hash_native(node, dialect, ops)
        elif isinstance(node, exp.AggFunc):
            if not isinstance(node.parent, exp.Window):
                _add_aggregate(node, dialect, ops)
            # else: this aggregate call is the windowed function itself
            # (SUM(...) OVER (...)) -- already carried by the `window` entry,
            # not a separate `aggregate` entry for the same call.
        elif isinstance(node, (exp.CTE, exp.Subquery)):
            _add_subquery_cte(node, dialect, ops)
        elif isinstance(node, (exp.Union, exp.Except, exp.Intersect)):
            _add_set_op(node, ops)
        elif isinstance(node, exp.Unnest):
            _add_unnest(node, dialect, ops)
        elif isinstance(node, exp.Lateral) and isinstance(node.this, exp.Explode):
            _add_unnest_lateral_flatten(node, dialect, ops)
        elif isinstance(node, exp.Dot) and _is_call_dot(node):
            _add_name_based(node, dialect, ops)
        elif isinstance(node, exp.Anonymous) and not isinstance(node.parent, exp.Dot):
            _add_name_based(node, dialect, ops)

    return ops


# --- Select-scoped: rename / compute / wildcard_select -----------------------------------


def _add_projections(select: exp.Select, dialect: str | None, ops: Operations) -> None:
    for item in select.expressions:
        if isinstance(item, exp.Alias):
            value = item.this
            if isinstance(value, exp.Column) and not isinstance(value.this, exp.Star):
                ops["rename"].append({"source": value.name, "output": item.alias})
            else:
                entry: dict[str, Any] = {
                    "output": item.alias,
                    "expression_summary": expression_summary(value, dialect),
                }
                cols = source_columns(value)
                if cols:
                    entry["source_columns"] = cols
                ops["compute"].append(entry)
        elif isinstance(item, exp.Star):
            ops["wildcard_select"].append(_wildcard_entry(item))
        elif isinstance(item, exp.Column) and isinstance(item.this, exp.Star):
            entry = {"kind": "qualified_star"}
            if item.table:
                entry["qualifier"] = item.table
            ops["wildcard_select"].append(entry)
        # A bare, unaliased Column (`SELECT cust_id FROM ...`) or any other
        # unaliased expression isn't tagged -- nothing changed, nothing to
        # tag (docs/grammar.md -> rename, edge cases).


def _wildcard_entry(star: exp.Star) -> dict[str, Any]:
    entry: dict[str, Any] = {"kind": "star"}
    except_cols = star.args.get("except_")
    if except_cols:
        entry["except_columns"] = [c.name for c in except_cols]
    return entry


# --- Select-scoped: join -------------------------------------------------------------------


def _add_joins(select: exp.Select, dialect: str | None, ops: Operations) -> None:
    from_ = select.args.get("from_") or select.args.get("from")
    steps: list[exp.Expression] = []
    if from_ is not None:
        steps.append(from_.this)
    joins = select.args.get("joins") or []
    for join in joins:
        steps.append(join.this)

    for i, join in enumerate(joins):
        left_name = _table_name(steps[i])
        right_name = _table_name(steps[i + 1])
        if left_name is None or right_name is None:
            continue  # not a table-to-table join (e.g. joined onto an UNNEST)
        side = join.args.get("side")
        kind = join.args.get("kind")
        entry: dict[str, Any] = {
            "kind": (side or kind or "inner").lower(),
            "tables": [left_name, right_name],
        }
        on = join.args.get("on")
        if on is not None:
            keys = [eq.this.name for eq in on.find_all(exp.EQ) if isinstance(eq.this, exp.Column)]
            if keys:
                entry["keys"] = keys
        ops["join"].append(entry)


def _table_name(node: exp.Expression) -> str | None:
    if isinstance(node, exp.Table):
        return node.name
    if isinstance(node, exp.Subquery) and node.alias:
        return node.alias
    return None


# --- Select-scoped: filter -------------------------------------------------------------------


def _add_filter(select: exp.Select, dialect: str | None, ops: Operations) -> None:
    where = select.args.get("where")
    if where is not None:
        ops["filter"].append({"summary": expression_summary(where.this, dialect)})


# --- set_op ------------------------------------------------------------------------------


def _add_set_op(node: exp.Union | exp.Except | exp.Intersect, ops: Operations) -> None:
    if isinstance(node, exp.Union):
        kind = "union" if node.args.get("distinct") else "union_all"
    elif isinstance(node, exp.Except):
        kind = "except"
    else:
        kind = "intersect"
    ops["set_op"].append({"kind": kind})


# --- subquery_cte --------------------------------------------------------------------------


def _add_subquery_cte(node: exp.CTE | exp.Subquery, dialect: str | None, ops: Operations) -> None:
    entry: dict[str, Any] = {"kind": "cte" if isinstance(node, exp.CTE) else "subquery"}
    alias = node.alias
    if alias:
        entry["alias"] = alias
    entry["location"] = "with" if isinstance(node, exp.CTE) else _location_of(node)
    ops["subquery_cte"].append(entry)


def _location_of(node: exp.Expression) -> str:
    """Nearest structural container name for a Subquery/Unnest/Lateral node."""
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.With):
            return "with"
        if isinstance(parent, exp.Where):
            return "where"
        if isinstance(parent, exp.Join):
            on = parent.args.get("on")
            using = parent.args.get("using")
            if on is not None or using:
                return "join"
            # No ON/USING condition -- sqlglot represents a comma-join, a bare
            # `CROSS JOIN`, and (dialect-dependently) an implicit-condition
            # UNNEST join all as a conditionless Join node, indistinguishable
            # from each other at this layer. Read all of them as "from",
            # matching the comma-join example in docs/grammar.md -> unnest.
            # Implementation judgment call, not a gdt-specified rule.
            return "from"
        if isinstance(parent, exp.From):
            return "from"
        parent = parent.parent
    return "from"


# --- conditional -----------------------------------------------------------------------------


def _add_conditional_case(node: exp.Case, dialect: str | None, ops: Operations) -> None:
    entry: dict[str, Any] = {"branches": _case_branches(node, dialect)}
    output = alias_output(node)
    if output:
        entry["output"] = output
    operand = node.args.get("this")
    if operand is not None:
        entry["operand_summary"] = expression_summary(operand, dialect)
    default = node.args.get("default")
    if default is not None:
        entry["default"] = expression_summary(default, dialect)
    ops["conditional"].append(entry)


def _case_branches(node: exp.Case, dialect: str | None) -> list[dict[str, str]]:
    branches = []
    for if_ in node.args.get("ifs") or []:
        branches.append(
            {
                "condition": expression_summary(if_.this, dialect),
                "result": expression_summary(if_.args["true"], dialect),
            }
        )
    return branches


def _add_conditional_if(node: exp.If, dialect: str | None, ops: Operations) -> None:
    entry: dict[str, Any] = {
        "branches": [
            {
                "condition": expression_summary(node.this, dialect),
                "result": expression_summary(node.args["true"], dialect),
            }
        ]
    }
    output = alias_output(node)
    if output:
        entry["output"] = output
    false = node.args.get("false")
    if false is not None:
        entry["default"] = expression_summary(false, dialect)
    ops["conditional"].append(entry)


# --- cast --------------------------------------------------------------------------------


def _add_cast(node: exp.Cast, dialect: str | None, ops: Operations) -> None:
    entry: dict[str, Any] = {
        "source_summary": expression_summary(node.this, dialect),
        "target_type": node.to.this.value.lower(),
    }
    output = alias_output(node)
    if output:
        entry["output"] = output
    entry["safe"] = bool(isinstance(node, exp.TryCast) or node.args.get("safe"))
    cols = source_columns(node.this)
    if cols:
        entry["source_columns"] = cols
    ops["cast"].append(entry)


# --- aggregate ---------------------------------------------------------------------------


def _add_aggregate(node: exp.AggFunc, dialect: str | None, ops: Operations) -> None:
    argument, distinct = _unwrap_distinct(node.this if "this" in node.args else None)
    entry: dict[str, Any] = {
        "function": _sql_name(node),
        "argument_summary": expression_summary(argument, dialect) if argument is not None else "*",
    }
    output = alias_output(node)
    if output:
        entry["output"] = output
    entry["distinct"] = distinct
    group_keys = _enclosing_group_keys(node, dialect)
    if group_keys:
        entry["group_by_keys"] = group_keys
    cols = source_columns(argument) if argument is not None else []
    if cols:
        entry["source_columns"] = cols
    ops["aggregate"].append(entry)


def _unwrap_distinct(argument: exp.Expression | None) -> tuple[exp.Expression | None, bool]:
    if isinstance(argument, exp.Distinct):
        inner = argument.expressions[0] if argument.expressions else None
        return inner, True
    return argument, False


def _enclosing_group_keys(node: exp.Expression, dialect: str | None) -> list[str]:
    select = node.find_ancestor(exp.Select)
    if select is None:
        return []
    group = select.args.get("group")
    if group is None:
        return []
    return [expression_summary(e, dialect) for e in group.expressions]


# --- window --------------------------------------------------------------------------------


def _add_window(node: exp.Window, dialect: str | None, ops: Operations) -> None:
    func = node.this
    entry: dict[str, Any] = {"function": _sql_name(func)}
    output = alias_output(node)
    if output:
        entry["output"] = output
    partition_by = node.args.get("partition_by") or []
    if partition_by:
        entry["partition_by"] = [expression_summary(e, dialect) for e in partition_by]
    order = node.args.get("order")
    if order is not None and order.expressions:
        entry["order_by"] = [expression_summary(o.this, dialect) for o in order.expressions]
    spec = node.args.get("spec")
    if spec is not None:
        frame = _window_frame(spec)
        if frame:
            entry["frame"] = frame
    func_argument = func.this if "this" in func.args else None
    cols = source_columns(func_argument) if func_argument is not None else []
    if cols:
        entry["source_columns"] = cols
    ops["window"].append(entry)


def _window_frame(spec: exp.Expression) -> dict[str, str] | None:
    kind = spec.args.get("kind")
    if not kind:
        return None
    start = " ".join(p for p in (spec.args.get("start"), spec.args.get("start_side")) if p)
    end = " ".join(p for p in (spec.args.get("end"), spec.args.get("end_side")) if p)
    frame: dict[str, str] = {"kind": kind.lower()}
    if start:
        frame["start"] = start
    if end:
        frame["end"] = end
    return frame


def _sql_name(func: exp.Expression) -> str:
    if isinstance(func, exp.Anonymous):
        return str(func.this).lower()
    names = func.sql_names() if hasattr(func, "sql_names") else []
    if names:
        return names[0].lower()
    return type(func).__name__.lower()


# --- column_hash (AST-grounded) -------------------------------------------------------------


def _add_column_hash_native(
    node: exp.MD5 | exp.SHA | exp.SHA2 | exp.FarmFingerprint, dialect: str | None, ops: Operations
) -> None:
    argument = _hash_argument(node)
    entry: dict[str, Any] = {
        "function": _sql_name(node),
        "argument_summary": expression_summary(argument, dialect) if argument is not None else "",
    }
    output = alias_output(node)
    if output:
        entry["output"] = output
    bits = node.args.get("length")
    if bits is not None:
        entry["algorithm_bits"] = int(bits.this)
    cols = source_columns(argument) if argument is not None else []
    if cols:
        entry["source_columns"] = cols
    ops["column_hash"].append(entry)


def _hash_argument(node: exp.Expression) -> exp.Expression | None:
    if "this" in node.args and node.this is not None:
        return node.this
    exprs = node.args.get("expressions")
    if exprs:
        return exprs[0]
    return None


# --- json_parse ----------------------------------------------------------------------------


def _add_json_parse(node: exp.ParseJSON, dialect: str | None, ops: Operations) -> None:
    entry: dict[str, Any] = {"source_summary": expression_summary(node.this, dialect)}
    output = alias_output(node)
    if output:
        entry["output"] = output
    entry["safe"] = bool(node.args.get("safe"))
    cols = source_columns(node.this)
    if cols:
        entry["source_columns"] = cols
    ops["json_parse"].append(entry)


# --- json_extract ----------------------------------------------------------------------------


def _add_json_extract(
    node: exp.JSONExtract | exp.JSONExtractScalar, dialect: str | None, ops: Operations
) -> None:
    keys: list[str] = []
    cursor: exp.Expression = node
    while isinstance(cursor, (exp.JSONExtract, exp.JSONExtractScalar)):
        keys = _json_path_keys(cursor) + keys
        cursor = cursor.this
    source = cursor  # innermost non-JSONExtract source expression

    entry: dict[str, Any] = {
        "source_summary": expression_summary(source, dialect),
        "path": "$." + ".".join(keys) if keys else "$",
        "scalar": bool(isinstance(node, exp.JSONExtractScalar) or _cast_wraps(node)),
    }
    output = alias_output(node) or (alias_output(node.parent) if _cast_wraps(node) else None)
    if output:
        entry["output"] = output
    cols = source_columns(source)
    if cols:
        entry["source_columns"] = cols
    ops["json_extract"].append(entry)


def _cast_wraps(node: exp.Expression) -> bool:
    # docs/grammar.md's own worked example: Snowflake `payload:email::string`
    # parses as Cast(this=JSONExtract(...)) and is documented to normalize to
    # the *same* json_extract shape as Postgres `->>` (scalar: true) -- the
    # trailing cast is what signals scalar-ness for the colon-path operator,
    # which sqlglot otherwise always parses as the non-scalar exp.JSONExtract
    # regardless of what it's cast to. Implementation judgment call for any
    # cast target (not just string), since no other example is given.
    return isinstance(node.parent, exp.Cast)


def _json_path_keys(node: exp.JSONExtract | exp.JSONExtractScalar) -> list[str]:
    path = node.args.get("expression")
    if path is None or not isinstance(path, exp.JSONPath):
        return []
    return [p.this for p in path.expressions if isinstance(p, exp.JSONPathKey)]


# --- unnest ------------------------------------------------------------------------------


def _add_unnest(node: exp.Unnest, dialect: str | None, ops: Operations) -> None:
    exprs = node.args.get("expressions") or []
    source = exprs[0] if exprs else None
    entry: dict[str, Any] = {
        "source_summary": expression_summary(source, dialect) if source is not None else "",
    }
    alias = _unnest_alias(node)
    if alias:
        entry["alias"] = alias
    entry["ordinality"] = bool(node.args.get("offset"))
    entry["location"] = _location_of(node)
    cols = source_columns(source) if source is not None else []
    if cols:
        entry["source_columns"] = cols
    ops["unnest"].append(entry)


def _unnest_alias(node: exp.Unnest) -> str | None:
    table_alias = node.args.get("alias")
    if table_alias is None:
        return None
    columns = table_alias.args.get("columns") or []
    if columns:
        return columns[0].name
    if table_alias.this:
        return table_alias.this.name
    return None


def _add_unnest_lateral_flatten(node: exp.Lateral, dialect: str | None, ops: Operations) -> None:
    # Snowflake LATERAL FLATTEN(input => expr) -- exp.Lateral(this=exp.Explode(...)).
    # Not grounded in exp.Unnest itself; confidence caveat carried over from
    # docs/grammar.md's own "needs confirming against real parses" note for
    # this specific mapping.
    explode = node.this
    argument = explode.this
    if isinstance(argument, exp.Kwarg):
        argument = argument.expression
    entry: dict[str, Any] = {
        "source_summary": expression_summary(argument, dialect) if argument is not None else "",
    }
    table_alias = node.args.get("alias")
    if table_alias is not None:
        alias = table_alias.this.name if table_alias.this else None
        if not alias:
            columns = table_alias.args.get("columns") or []
            alias = columns[0].name if columns else None
        if alias:
            entry["alias"] = alias
    entry["ordinality"] = bool(node.args.get("ordinality"))
    entry["location"] = _location_of(node)
    cols = source_columns(argument) if argument is not None else []
    if cols:
        entry["source_columns"] = cols
    ops["unnest"].append(entry)


# --- ai_function / udf / column_hash (name-based fallback) -----------------------------------


def _is_call_dot(node: exp.Dot) -> bool:
    _, call_node = _unwrap_dot(node)
    return isinstance(call_node, exp.Func)


def _unwrap_dot(node: exp.Expression) -> tuple[list[str], exp.Expression]:
    parts: list[str] = []
    cursor = node
    while isinstance(cursor, exp.Dot):
        this = cursor.this
        parts.append(this.name if hasattr(this, "name") else str(this))
        cursor = cursor.expression
    return parts, cursor


def _call_arguments(call_node: exp.Expression) -> list[exp.Expression]:
    """Best-effort positional argument list for an arbitrary function-call node.

    Most Func subclasses (and Anonymous) keep their args in `.expressions`, but
    some dedicated multi-arg nodes (e.g. exp.GenerateText: `this`=model,
    `expression`=prompt) use named `this`/`expression` slots instead. Falls
    back to every Expression-typed arg value for anything else.
    """
    exprs = call_node.args.get("expressions")
    if exprs:
        return list(exprs)
    named = [call_node.args.get("this"), call_node.args.get("expression")]
    named = [a for a in named if isinstance(a, exp.Expression)]
    if named:
        return named
    return [v for v in call_node.args.values() if isinstance(v, exp.Expression)]


def _add_name_based(node: exp.Dot | exp.Anonymous, dialect: str | None, ops: Operations) -> None:
    namespace_parts, call_node = _unwrap_dot(node)
    unqualified = _sql_name(call_node)
    qualified = ".".join([*namespace_parts, unqualified]).lower() if namespace_parts else unqualified

    argument = _call_arguments(call_node)
    argument_summary = ", ".join(expression_summary(a, dialect) for a in argument)
    output = alias_output(node)
    cols: list[str] = []
    for a in argument:
        cols.extend(source_columns(a))
    deduped_cols = list(dict.fromkeys(cols))

    entry: dict[str, Any] = {"argument_summary": argument_summary}
    if output:
        entry["output"] = output
    if deduped_cols:
        entry["source_columns"] = deduped_cols

    if unqualified in COLUMN_HASH_FALLBACK_NAMES:
        entry["function"] = unqualified
        ops["column_hash"].append(entry)
        return

    if unqualified in AI_FUNCTION_NAMES or qualified in AI_FUNCTION_NAMES:
        entry["function"] = qualified
        ops["ai_function"].append(entry)
        return

    if isinstance(call_node, exp.Anonymous):
        entry["function"] = qualified
        ops["udf"].append(entry)
    # else: a recognized (non-Anonymous) builtin sqlglot already knows about
    # that isn't in the ai_function allowlist -- not a real UDF, don't tag it
    # (ADR 0003: udf is specifically the fallback for what sqlglot *doesn't*
    # recognize as a builtin).
