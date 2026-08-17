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
            if not _is_windowed(node):
                _add_aggregate(node, dialect, ops)
            # else: this aggregate call is the windowed function itself
            # (SUM(...) OVER (...), or SUM(...) IGNORE NULLS OVER (...)) --
            # already carried by the `window` entry, not a separate
            # `aggregate` entry for the same call.
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
    if from_ is None:
        return
    # Check the FROM clause's own base table once, up front, for the case
    # where it's *itself* a parenthesized join tree with nothing joining onto
    # it from outside (`FROM (b JOIN c ON ...) x`) -- the loop below only
    # ever looks at join *targets*, so this is the one step it would never see.
    base_nested = _nested_join_table(from_.this)
    if base_nested is not None:
        _add_join_chain(base_nested, base_nested.args["joins"], ops)
    _add_join_chain(from_.this, select.args.get("joins") or [], ops)


def _add_join_chain(from_step: exp.Expression, joins: list[exp.Join], ops: Operations) -> None:
    """Emit one entry per pairwise join in `joins`, then recurse into any join
    *target* that is itself a parenthesized join tree (`a JOIN (b JOIN c ON
    ...) ON ...` parses as a Join whose `.this` is a Table/Subquery that
    carries its own nested `joins` list) so those inner joins aren't silently
    dropped.

    Deliberately does NOT re-check `from_step` itself here (only the targets
    introduced by `joins`, i.e. `steps[1:]`) -- `from_step` is the exact node
    this call was handed to recurse into, and its `.args['joins']` doesn't
    change just because we're now processing it, so re-scanning it would
    match again immediately and recurse forever. Any nesting on `from_step`'s
    own side is the caller's responsibility to have checked once, before
    calling in (see `_add_joins`'s `base_nested` check).
    """
    steps = [from_step] + [j.this for j in joins]

    for i, join in enumerate(joins):
        left_name = _table_name(steps[i])
        right_name = _table_name(steps[i + 1])
        if left_name is None or right_name is None:
            continue  # not a table-to-table join (e.g. joined onto an UNNEST)
        kind = _join_kind(join)
        if kind is None:
            # SEMI / ANTI / bare OUTER / any other combination the gdt schema's
            # join.kind enum (inner/left/right/full/cross) has no shape for --
            # a known representability gap, same category as the non-equi-join
            # gap already documented in docs/grammar.md -> join edge cases.
            # Don't guess a kind; just don't tag this one.
            continue
        entry: dict[str, Any] = {"kind": kind, "tables": [left_name, right_name]}
        keys = _join_keys(join)
        if keys:
            entry["keys"] = keys
        ops["join"].append(entry)

    for step in steps[1:]:
        nested_table = _nested_join_table(step)
        if nested_table is not None:
            _add_join_chain(nested_table, nested_table.args["joins"], ops)


def _join_kind(join: exp.Join) -> str | None:
    side = (join.args.get("side") or "").upper()
    kind = (join.args.get("kind") or "").upper()
    if side == "LEFT":
        return "left"
    if side == "RIGHT":
        return "right"
    if side == "FULL":
        return "full"
    if not side and kind == "CROSS":
        return "cross"
    if not side and kind in ("", "INNER"):
        return "inner"
    return None


def _join_keys(join: exp.Join) -> list[str]:
    on = join.args.get("on")
    if on is not None:
        return [eq.this.name for eq in on.find_all(exp.EQ) if isinstance(eq.this, exp.Column)]
    using = join.args.get("using")
    if using:
        return [u.name for u in using]
    return []


def _table_name(node: exp.Expression) -> str | None:
    if isinstance(node, exp.Table):
        return node.name
    if isinstance(node, exp.Subquery):
        if node.alias:
            return node.alias
        if isinstance(node.this, exp.Table):
            return node.this.name
    return None


def _nested_join_table(node: exp.Expression) -> exp.Table | None:
    """A Table (possibly Subquery-wrapped) carrying its own nested join chain."""
    table = node.this if isinstance(node, exp.Subquery) else node
    if isinstance(table, exp.Table) and table.args.get("joins"):
        return table
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
    """Nearest structural container name for a Subquery/Unnest/Lateral node.

    `location` is a free-form string in the gdt schema (no enum), so this can
    return a value more specific than "from" whenever that's what's actually
    true -- it must not claim "from" for something that isn't a FROM-clause
    table source (docs/grammar.md's own subquery_cte example only documents
    from/where; the values below extend that set honestly rather than
    collapsing everything unrecognized onto "from").
    """
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.With):
            return "with"
        if isinstance(parent, exp.Where):
            return "where"
        if isinstance(parent, exp.Having):
            return "having"
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
        if isinstance(parent, exp.Select):
            # Reached the enclosing Select without passing through From/Where/
            # Join/Having -- this node is a projection-list expression (a
            # scalar subquery or a bare UNNEST() in the SELECT list), not a
            # FROM-clause table source. Reporting "from" here would actively
            # mislead a consumer; "select" is honest about what it actually is.
            return "select"
        parent = parent.parent
    return "select"


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
    arguments, distinct = _unwrap_distinct(node.this if "this" in node.args else None)
    # Two-argument aggregates (CORR, COVAR_POP/SAMP, REGR_*) carry their second
    # operand in the `expression` slot, not inside `this` -- without this, that
    # column silently vanishes from both argument_summary and source_columns.
    second = node.args.get("expression")
    if isinstance(second, exp.Expression):
        arguments = [*arguments, second]

    entry: dict[str, Any] = {
        "function": _sql_name(node),
        "argument_summary": ", ".join(expression_summary(a, dialect) for a in arguments) if arguments else "*",
    }
    output = alias_output(node)
    if output:
        entry["output"] = output
    entry["distinct"] = distinct
    group_keys = _enclosing_group_keys(node, dialect)
    if group_keys:
        entry["group_by_keys"] = group_keys
    cols: list[str] = []
    for a in arguments:
        cols.extend(source_columns(a))
    deduped_cols = list(dict.fromkeys(cols))
    if deduped_cols:
        entry["source_columns"] = deduped_cols
    ops["aggregate"].append(entry)


def _unwrap_distinct(argument: exp.Expression | None) -> tuple[list[exp.Expression], bool]:
    if isinstance(argument, exp.Distinct):
        return list(argument.expressions), True
    if argument is None:
        return [], False
    return [argument], False


def _enclosing_group_keys(node: exp.Expression, dialect: str | None) -> list[str]:
    select = node.find_ancestor(exp.Select)
    if select is None:
        return []
    group = select.args.get("group")
    if group is None:
        return []
    if group.expressions:
        return [expression_summary(e, dialect) for e in group.expressions]
    # A plain GROUP BY has no top-level `expressions` when the query uses
    # ROLLUP/CUBE/GROUPING SETS instead -- those store their columns under
    # separate arg keys (`rollup`/`cube`/`grouping_sets`), not `expressions`.
    # Without this, an aggregate under any of these common grouping forms
    # would report no group_by_keys at all, indistinguishable from a bare
    # scalar aggregate with no GROUP BY clause whatsoever.
    keys: list[str] = []
    seen: set[str] = set()
    for wrapper_key in ("rollup", "cube", "grouping_sets"):
        for wrapper in group.args.get(wrapper_key) or []:
            for item in wrapper.expressions:
                if isinstance(item, exp.Tuple) and not item.expressions:
                    continue  # the empty grouping set "()" -- no column to summarize
                if isinstance(item, exp.Paren):
                    item = item.this
                summary = expression_summary(item, dialect)
                if summary not in seen:
                    seen.add(summary)
                    keys.append(summary)
    return keys


# --- window --------------------------------------------------------------------------------


def _is_windowed(node: exp.Expression) -> bool:
    """True if `node` is the (possibly IGNORE/RESPECT NULLS-wrapped) function
    inside an exp.Window -- i.e. already carried by a `window` entry, so it
    must not also become a standalone `aggregate` entry for the same call.
    """
    parent = node.parent
    if isinstance(parent, (exp.IgnoreNulls, exp.RespectNulls)):
        parent = parent.parent
    return isinstance(parent, exp.Window)


def _unwrap_null_treatment(node: exp.Expression) -> exp.Expression:
    """Strip an IGNORE NULLS / RESPECT NULLS wrapper to the real function call."""
    if isinstance(node, (exp.IgnoreNulls, exp.RespectNulls)):
        return node.this
    return node


def _add_window(node: exp.Window, dialect: str | None, ops: Operations) -> None:
    func = _unwrap_null_treatment(node.this)
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
    if isinstance(bits, exp.Literal) and bits.is_number:
        entry["algorithm_bits"] = int(bits.this)
    # else: a non-literal bit-length (a column, a parameter, ...) -- omit the
    # field rather than crash; algorithm_bits is documented as "if specified"
    # and a dynamic value isn't a fixed spec-time constant to report.
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
        "path": _render_json_path(keys),
        "scalar": bool(isinstance(node, exp.JSONExtractScalar) or _cast_wraps(node)),
    }
    output = alias_output(node) or (alias_output(node.parent) if _cast_wraps(node) else None)
    if output:
        entry["output"] = output
    cols = source_columns(source)
    if cols:
        entry["source_columns"] = cols
    ops["json_extract"].append(entry)


# Target types a JSONExtract could be cast to that are themselves semi-
# structured/nested, not scalar -- casting to one of these doesn't make the
# extraction scalar-returning the way `::string`/`::number` does.
_NON_SCALAR_CAST_TYPES = frozenset(
    {
        exp.DataType.Type.JSON,
        exp.DataType.Type.JSONB,
        exp.DataType.Type.VARIANT,
        exp.DataType.Type.OBJECT,
        exp.DataType.Type.ARRAY,
        exp.DataType.Type.STRUCT,
        exp.DataType.Type.MAP,
    }
)


def _cast_wraps(node: exp.Expression) -> bool:
    # docs/grammar.md's own worked example: Snowflake `payload:email::string`
    # parses as Cast(this=JSONExtract(...)) and is documented to normalize to
    # the *same* json_extract shape as Postgres `->>` (scalar: true) -- the
    # trailing cast is what signals scalar-ness for the colon-path operator,
    # which sqlglot otherwise always parses as the non-scalar exp.JSONExtract
    # regardless of what it's cast to. But a cast to an explicitly non-scalar
    # type (`::variant`, `::object`, `::array`, ...) is not evidence of
    # scalar-ness -- only a cast to something else is.
    parent = node.parent
    if not isinstance(parent, exp.Cast):
        return False
    return parent.to.this not in _NON_SCALAR_CAST_TYPES


def _json_path_keys(node: exp.JSONExtract | exp.JSONExtractScalar) -> list[str]:
    path = node.args.get("expression")
    if path is None or not isinstance(path, exp.JSONPath):
        return []
    keys: list[str] = []
    for p in path.expressions:
        if isinstance(p, exp.JSONPathKey):
            keys.append(str(p.this))
        elif isinstance(p, exp.JSONPathSubscript):
            # Marked distinctly from a plain key so _render_json_path can join
            # it as "[0]" rather than ".0" -- a subscript is not a named hop.
            keys.append(f"[{p.this}]")
    return keys


def _render_json_path(keys: list[str]) -> str:
    if not keys:
        return "$"
    parts = ["$"]
    for key in keys:
        if key.startswith("["):
            parts.append(key)
        else:
            parts.append(f".{key}")
    return "".join(parts)


# --- unnest ------------------------------------------------------------------------------


def _add_unnest(node: exp.Unnest, dialect: str | None, ops: Operations) -> None:
    # A parallel/"zip" unnest (UNNEST(a, b) AS t(x, y), Postgres-style) lists
    # more than one array; GDT's unnest shape is one-array-per-entry, so each
    # array gets its own entry paired positionally with its own alias column
    # -- reading only exprs[0] silently discarded every array after the first.
    exprs = node.args.get("expressions") or []
    aliases = _unnest_aliases(node, len(exprs))
    ordinality = bool(node.args.get("offset"))
    location = _location_of(node)
    for source, alias in zip(exprs, aliases):
        entry: dict[str, Any] = {"source_summary": expression_summary(source, dialect)}
        if alias:
            entry["alias"] = alias
        entry["ordinality"] = ordinality
        entry["location"] = location
        cols = source_columns(source)
        if cols:
            entry["source_columns"] = cols
        ops["unnest"].append(entry)
    if not exprs:
        entry = {"source_summary": "", "ordinality": ordinality, "location": location}
        ops["unnest"].append(entry)


def _unnest_aliases(node: exp.Unnest, count: int) -> list[str | None]:
    table_alias = node.args.get("alias")
    if table_alias is None:
        return [None] * count
    columns = table_alias.args.get("columns") or []
    if len(columns) == count:
        return [c.name for c in columns]
    if columns:
        # Count mismatch (e.g. WITH ORDINALITY's offset column already
        # stripped out of `columns` elsewhere) -- fall back to the single
        # alias name for every array rather than guessing a pairing.
        return [columns[0].name] * count
    if table_alias.this:
        return [table_alias.this.name] * count
    return [None] * count


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
    # exp.Dot.flatten() yields every leaf left-to-right (namespace identifiers
    # first, the call node last) -- a hand-rolled `while isinstance(cursor,
    # exp.Dot): cursor = cursor.expression` loop is wrong here, because a 3+
    # level qualified call (`a.b.c(...)`) nests the extra qualifiers on the
    # *`.this`* side (Dot(this=Dot(this=a, expression=b), expression=c(...))),
    # not the `.expression` side, so that loop only ever takes one step and
    # silently drops every segment but the innermost.
    if not isinstance(node, exp.Dot):
        return [], node
    *namespace, call_node = list(node.flatten())
    parts = [n.name if hasattr(n, "name") else str(n) for n in namespace]
    return parts, call_node


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
