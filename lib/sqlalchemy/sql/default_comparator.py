# sql/default_comparator.py
# Copyright (C) 2005-2022 the SQLAlchemy authors and contributors
# <see AUTHORS file>
#
# This module is part of SQLAlchemy and is released under
# the MIT License: https://www.opensource.org/licenses/mit-license.php

"""Default implementation of SQL comparison operations.
"""

import typing
from typing import Any
from typing import Callable
from typing import Dict
from typing import NoReturn
from typing import Optional
from typing import Tuple
from typing import Type
from typing import Union

from . import coercions
from . import operators
from . import roles
from . import type_api
from .elements import and_
from .elements import BinaryExpression
from .elements import ClauseList
from .elements import CollationClause
from .elements import CollectionAggregate
from .elements import False_
from .elements import Null
from .elements import or_
from .elements import True_
from .elements import UnaryExpression
from .operators import OperatorType
from .. import exc
from .. import util

_T = typing.TypeVar("_T", bound=Any)

if typing.TYPE_CHECKING:
    from .elements import ColumnElement
    from .sqltypes import TypeEngine


def _boolean_compare(
    expr: "ColumnElement",
    op: OperatorType,
    obj: roles.BinaryElementRole,
    *,
    negate_op: Optional[OperatorType] = None,
    reverse: bool = False,
    _python_is_types=(util.NoneType, bool),
    _any_all_expr=False,
    result_type: Optional[
        Union[Type["TypeEngine[bool]"], "TypeEngine[bool]"]
    ] = None,
    **kwargs: Any,
) -> BinaryExpression[bool]:

    if result_type is None:
        result_type = type_api.BOOLEANTYPE

    if isinstance(obj, _python_is_types + (Null, True_, False_)):
        # allow x ==/!= True/False to be treated as a literal.
        # this comes out to "== / != true/false" or "1/0" if those
        # constants aren't supported and works on all platforms
        if op in (operators.eq, operators.ne) and isinstance(
            obj, (bool, True_, False_)
        ):
            return BinaryExpression(
                expr,
                coercions.expect(roles.ConstExprRole, obj),
                op,
                type_=result_type,
                negate=negate_op,
                modifiers=kwargs,
            )
        elif op in (
            operators.is_distinct_from,
            operators.is_not_distinct_from,
        ):
            return BinaryExpression(
                expr,
                coercions.expect(roles.ConstExprRole, obj),
                op,
                type_=result_type,
                negate=negate_op,
                modifiers=kwargs,
            )
        elif _any_all_expr:
            obj = coercions.expect(
                roles.ConstExprRole, element=obj, operator=op, expr=expr
            )
        else:
            # all other None uses IS, IS NOT
            if op in (operators.eq, operators.is_):
                return BinaryExpression(
                    expr,
                    coercions.expect(roles.ConstExprRole, obj),
                    operators.is_,
                    negate=operators.is_not,
                    type_=result_type,
                )
            elif op in (operators.ne, operators.is_not):
                return BinaryExpression(
                    expr,
                    coercions.expect(roles.ConstExprRole, obj),
                    operators.is_not,
                    negate=operators.is_,
                    type_=result_type,
                )
            else:
                raise exc.ArgumentError(
                    "Only '=', '!=', 'is_()', 'is_not()', "
                    "'is_distinct_from()', 'is_not_distinct_from()' "
                    "operators can be used with None/True/False"
                )
    else:
        obj = coercions.expect(
            roles.BinaryElementRole, element=obj, operator=op, expr=expr
        )

    if reverse:
        return BinaryExpression(
            obj,
            expr,
            op,
            type_=result_type,
            negate=negate_op,
            modifiers=kwargs,
        )
    else:
        return BinaryExpression(
            expr,
            obj,
            op,
            type_=result_type,
            negate=negate_op,
            modifiers=kwargs,
        )


def _custom_op_operate(expr, op, obj, reverse=False, result_type=None, **kw):
    if result_type is None:
        if op.return_type:
            result_type = op.return_type
        elif op.is_comparison:
            result_type = type_api.BOOLEANTYPE

    return _binary_operate(
        expr, op, obj, reverse=reverse, result_type=result_type, **kw
    )


def _binary_operate(
    expr: "ColumnElement",
    op: OperatorType,
    obj: roles.BinaryElementRole,
    *,
    reverse=False,
    result_type: Optional[
        Union[Type["TypeEngine[_T]"], "TypeEngine[_T]"]
    ] = None,
    **kw: Any,
) -> BinaryExpression[_T]:

    coerced_obj = coercions.expect(
        roles.BinaryElementRole, obj, expr=expr, operator=op
    )

    if reverse:
        left, right = coerced_obj, expr
    else:
        left, right = expr, coerced_obj

    if result_type is None:
        op, result_type = left.comparator._adapt_expression(
            op, right.comparator
        )

    return BinaryExpression(left, right, op, type_=result_type, modifiers=kw)


def _conjunction_operate(expr, op, other, **kw) -> "ColumnElement":
    if op is operators.and_:
        return and_(expr, other)
    elif op is operators.or_:
        return or_(expr, other)
    else:
        raise NotImplementedError()


def _scalar(expr, op, fn, **kw) -> "ColumnElement":
    return fn(expr)


def _in_impl(expr, op, seq_or_selectable, negate_op, **kw) -> "ColumnElement":
    seq_or_selectable = coercions.expect(
        roles.InElementRole, seq_or_selectable, expr=expr, operator=op
    )
    if "in_ops" in seq_or_selectable._annotations:
        op, negate_op = seq_or_selectable._annotations["in_ops"]

    return _boolean_compare(
        expr, op, seq_or_selectable, negate_op=negate_op, **kw
    )


def _getitem_impl(expr, op, other, **kw) -> "ColumnElement":
    if isinstance(expr.type, type_api.INDEXABLE):
        other = coercions.expect(
            roles.BinaryElementRole, other, expr=expr, operator=op
        )
        return _binary_operate(expr, op, other, **kw)
    else:
        _unsupported_impl(expr, op, other, **kw)


def _unsupported_impl(expr, op, *arg, **kw) -> NoReturn:
    raise NotImplementedError(
        "Operator '%s' is not supported on " "this expression" % op.__name__
    )


def _inv_impl(expr, op, **kw) -> "ColumnElement":
    """See :meth:`.ColumnOperators.__inv__`."""

    # undocumented element currently used by the ORM for
    # relationship.contains()
    if hasattr(expr, "negation_clause"):
        return expr.negation_clause
    else:
        return expr._negate()


def _neg_impl(expr, op, **kw) -> "ColumnElement":
    """See :meth:`.ColumnOperators.__neg__`."""
    return UnaryExpression(expr, operator=operators.neg, type_=expr.type)


def _match_impl(expr, op, other, **kw) -> "ColumnElement":
    """See :meth:`.ColumnOperators.match`."""

    return _boolean_compare(
        expr,
        operators.match_op,
        coercions.expect(
            roles.BinaryElementRole,
            other,
            expr=expr,
            operator=operators.match_op,
        ),
        result_type=type_api.MATCHTYPE,
        negate_op=operators.not_match_op
        if op is operators.match_op
        else operators.match_op,
        **kw,
    )


def _distinct_impl(expr, op, **kw) -> "ColumnElement":
    """See :meth:`.ColumnOperators.distinct`."""
    return UnaryExpression(
        expr, operator=operators.distinct_op, type_=expr.type
    )


def _between_impl(expr, op, cleft, cright, **kw) -> "ColumnElement":
    """See :meth:`.ColumnOperators.between`."""
    return BinaryExpression(
        expr,
        ClauseList(
            coercions.expect(
                roles.BinaryElementRole,
                cleft,
                expr=expr,
                operator=operators.and_,
            ),
            coercions.expect(
                roles.BinaryElementRole,
                cright,
                expr=expr,
                operator=operators.and_,
            ),
            operator=operators.and_,
            group=False,
            group_contents=False,
        ),
        op,
        negate=operators.not_between_op
        if op is operators.between_op
        else operators.between_op,
        modifiers=kw,
    )


def _collate_impl(expr, op, collation, **kw) -> "ColumnElement":
    return CollationClause._create_collation_expression(expr, collation)


def _regexp_match_impl(expr, op, pattern, flags, **kw) -> "ColumnElement":
    if flags is not None:
        flags = coercions.expect(
            roles.BinaryElementRole,
            flags,
            expr=expr,
            operator=operators.regexp_replace_op,
        )
    return _boolean_compare(
        expr,
        op,
        pattern,
        flags=flags,
        negate_op=operators.not_regexp_match_op
        if op is operators.regexp_match_op
        else operators.regexp_match_op,
        **kw,
    )


def _regexp_replace_impl(
    expr, op, pattern, replacement, flags, **kw
) -> "ColumnElement":
    replacement = coercions.expect(
        roles.BinaryElementRole,
        replacement,
        expr=expr,
        operator=operators.regexp_replace_op,
    )
    if flags is not None:
        flags = coercions.expect(
            roles.BinaryElementRole,
            flags,
            expr=expr,
            operator=operators.regexp_replace_op,
        )
    return _binary_operate(
        expr, op, pattern, replacement=replacement, flags=flags, **kw
    )


# a mapping of operators with the method they use, along with
# additional keyword arguments to be passed
operator_lookup: Dict[
    str, Tuple[Callable[..., "ColumnElement"], util.immutabledict]
] = {
    "and_": (_conjunction_operate, util.EMPTY_DICT),
    "or_": (_conjunction_operate, util.EMPTY_DICT),
    "inv": (_inv_impl, util.EMPTY_DICT),
    "add": (_binary_operate, util.EMPTY_DICT),
    "mul": (_binary_operate, util.EMPTY_DICT),
    "sub": (_binary_operate, util.EMPTY_DICT),
    "div": (_binary_operate, util.EMPTY_DICT),
    "mod": (_binary_operate, util.EMPTY_DICT),
    "truediv": (_binary_operate, util.EMPTY_DICT),
    "floordiv": (_binary_operate, util.EMPTY_DICT),
    "custom_op": (_custom_op_operate, util.EMPTY_DICT),
    "json_path_getitem_op": (_binary_operate, util.EMPTY_DICT),
    "json_getitem_op": (_binary_operate, util.EMPTY_DICT),
    "concat_op": (_binary_operate, util.EMPTY_DICT),
    "any_op": (
        _scalar,
        util.immutabledict({"fn": CollectionAggregate._create_any}),
    ),
    "all_op": (
        _scalar,
        util.immutabledict({"fn": CollectionAggregate._create_all}),
    ),
    "lt": (_boolean_compare, util.immutabledict({"negate_op": operators.ge})),
    "le": (_boolean_compare, util.immutabledict({"negate_op": operators.gt})),
    "ne": (_boolean_compare, util.immutabledict({"negate_op": operators.eq})),
    "gt": (_boolean_compare, util.immutabledict({"negate_op": operators.le})),
    "ge": (_boolean_compare, util.immutabledict({"negate_op": operators.lt})),
    "eq": (_boolean_compare, util.immutabledict({"negate_op": operators.ne})),
    "is_distinct_from": (
        _boolean_compare,
        util.immutabledict({"negate_op": operators.is_not_distinct_from}),
    ),
    "is_not_distinct_from": (
        _boolean_compare,
        util.immutabledict({"negate_op": operators.is_distinct_from}),
    ),
    "like_op": (
        _boolean_compare,
        util.immutabledict({"negate_op": operators.not_like_op}),
    ),
    "ilike_op": (
        _boolean_compare,
        util.immutabledict({"negate_op": operators.not_ilike_op}),
    ),
    "not_like_op": (
        _boolean_compare,
        util.immutabledict({"negate_op": operators.like_op}),
    ),
    "not_ilike_op": (
        _boolean_compare,
        util.immutabledict({"negate_op": operators.ilike_op}),
    ),
    "contains_op": (
        _boolean_compare,
        util.immutabledict({"negate_op": operators.not_contains_op}),
    ),
    "startswith_op": (
        _boolean_compare,
        util.immutabledict({"negate_op": operators.not_startswith_op}),
    ),
    "endswith_op": (
        _boolean_compare,
        util.immutabledict({"negate_op": operators.not_endswith_op}),
    ),
    "desc_op": (
        _scalar,
        util.immutabledict({"fn": UnaryExpression._create_desc}),
    ),
    "asc_op": (
        _scalar,
        util.immutabledict({"fn": UnaryExpression._create_asc}),
    ),
    "nulls_first_op": (
        _scalar,
        util.immutabledict({"fn": UnaryExpression._create_nulls_first}),
    ),
    "nulls_last_op": (
        _scalar,
        util.immutabledict({"fn": UnaryExpression._create_nulls_last}),
    ),
    "in_op": (
        _in_impl,
        util.immutabledict({"negate_op": operators.not_in_op}),
    ),
    "not_in_op": (
        _in_impl,
        util.immutabledict({"negate_op": operators.in_op}),
    ),
    "is_": (
        _boolean_compare,
        util.immutabledict({"negate_op": operators.is_}),
    ),
    "is_not": (
        _boolean_compare,
        util.immutabledict({"negate_op": operators.is_not}),
    ),
    "collate": (_collate_impl, util.EMPTY_DICT),
    "match_op": (_match_impl, util.EMPTY_DICT),
    "not_match_op": (_match_impl, util.EMPTY_DICT),
    "distinct_op": (_distinct_impl, util.EMPTY_DICT),
    "between_op": (_between_impl, util.EMPTY_DICT),
    "not_between_op": (_between_impl, util.EMPTY_DICT),
    "neg": (_neg_impl, util.EMPTY_DICT),
    "getitem": (_getitem_impl, util.EMPTY_DICT),
    "lshift": (_unsupported_impl, util.EMPTY_DICT),
    "rshift": (_unsupported_impl, util.EMPTY_DICT),
    "contains": (_unsupported_impl, util.EMPTY_DICT),
    "regexp_match_op": (_regexp_match_impl, util.EMPTY_DICT),
    "not_regexp_match_op": (_regexp_match_impl, util.EMPTY_DICT),
    "regexp_replace_op": (_regexp_replace_impl, util.EMPTY_DICT),
}
