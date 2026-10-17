"""Typed front end and Python renderer for a deliberately small TLA+ fragment.

The module does not try to parse full TLA+. It recognises the grammar stated
in the accompanying manuscript, produces a typed AST and a small model IR, and
renders readable Python. The verifier uses the IR evaluator below; it never
executes user-derived generated text in the web process.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, TypeAlias


class TranslationError(ValueError):
    """Raised when a source model is outside the documented fragment."""


IDENT = r"[A-Za-z_][A-Za-z_0-9]*"
_IDENT_RE = re.compile(IDENT)
Value: TypeAlias = int | bool
TypeName: TypeAlias = str  # Exactly "int" or "bool" in a validated model.


# This is a language contract, not a claim about the full TLA+ language.  It is
# returned in evidence bundles so that a reader can connect each accepted
# source form with its AST/IR representation and emitted Python shape.
SYNTAX_CONTRACT_ID = "restricted_tla_to_python_v1"
_RESERVED_IDENTIFIERS = frozenset(
    {
        "IF",
        "THEN",
        "ELSE",
        "TRUE",
        "FALSE",
        "UNCHANGED",
        "VARIABLE",
        "VARIABLES",
        "EXTENDS",
        "Init",
        "Next",
    }
)
_SYNTAX_FORMS: tuple[dict[str, str], ...] = (
    {
        "source": "\\* line comment",
        "parser": "definition collection removes text from \\* to end of line",
        "ir": "no node",
        "python": "no emitted text",
    },
    {
        "source": "---- MODULE Name ----, EXTENDS Name, ====",
        "parser": "top-level framing is recognised and ignored",
        "ir": "no imported-module semantics",
        "python": "no emitted text",
    },
    {
        "source": "VARIABLE x | VARIABLES x, y",
        "parser": "_get_vars records unique non-reserved scalar names",
        "ir": "ModelIR.variables",
        "python": "INITIAL_STATE keys and state['name'] reads",
    },
    {
        "source": "Name == body",
        "parser": "_blocks collects one named top-level definition",
        "ir": "Init, selected ActionIR, or Next reference",
        "python": "Init/action/Next-specific lowering",
    },
    {
        "source": "Init == x = Integer | TRUE | FALSE (/\\ ...)*",
        "parser": "one literal assignment is required for every variable",
        "ir": "ModelIR.initial_state and variable_types",
        "python": "INITIAL_STATE = {'x': value, ...}",
    },
    {
        "source": "Action == Clause (/\\ Clause)*",
        "parser": "_split_action_clauses separates only top-level conjunctions",
        "ir": "ActionIR(name, guards, updates)",
        "python": "one labelled if block in next_transitions",
    },
    {
        "source": "Boolean guard Expr",
        "parser": "recursive-descent expression parser plus Boolean type check",
        "ir": "ActionIR.guards containing typed ASTs",
        "python": "if (<rendered guard>):",
    },
    {
        "source": "x' = Expr",
        "parser": "primed name is legal only on an action-assignment left side",
        "ir": "ActionIR.updates['x'] = typed AST",
        "python": "updated['x'] = <rendered expression>",
    },
    {
        "source": "UNCHANGED x | UNCHANGED x, y | UNCHANGED <<x, y>>",
        "parser": "expands each named variable to an old-state read",
        "ir": "VariableExpr for every preserved variable",
        "python": "updated['x'] = state['x']",
    },
    {
        "source": "Next == Action | Action \\/ Action ...",
        "parser": "_parse_next accepts unique defined action names only",
        "ir": "ModelIR.next_actions in source order",
        "python": "ordered action blocks append labelled transitions",
    },
    {
        "source": "Integer",
        "parser": "integer token and LiteralExpr(int)",
        "ir": "LiteralExpr",
        "python": "decimal integer literal",
    },
    {
        "source": "TRUE | FALSE",
        "parser": "keyword token and LiteralExpr(bool)",
        "ir": "LiteralExpr",
        "python": "True | False",
    },
    {
        "source": "Name in an expression",
        "parser": "name token resolved through the declared-variable table",
        "ir": "VariableExpr(name)",
        "python": "state['name']",
    },
    {
        "source": "( Expr )",
        "parser": "recursive call between matched parentheses",
        "ir": "the enclosed AST; grouping changes tree shape",
        "python": "renderer parenthesises compound expressions",
    },
    {
        "source": "- Expr",
        "parser": "_parse_unary builds UnaryExpr('-')",
        "ir": "UnaryExpr",
        "python": "(-<expression>)",
    },
    {
        "source": "~ Expr",
        "parser": "_parse_unary builds UnaryExpr('~')",
        "ir": "UnaryExpr",
        "python": "(not <expression>)",
    },
    {
        "source": "left + right | left - right | left * right | left % right",
        "parser": "left-associative additive or multiplicative precedence level",
        "ir": "BinaryExpr with integer operands",
        "python": "same Python arithmetic operator",
    },
    {
        "source": "left = right | left /= right",
        "parser": "one comparison is accepted after an additive expression",
        "ir": "BinaryExpr with equal operand types",
        "python": "== | !=",
    },
    {
        "source": "left < right | <= | > | >= right",
        "parser": "one comparison is accepted after an additive expression",
        "ir": "BinaryExpr with integer operands",
        "python": "same Python comparison operator",
    },
    {
        "source": "left /\\ right",
        "parser": "_parse_and folds left-associatively",
        "ir": "BinaryExpr('/\\') with Boolean operands",
        "python": "(<left> and <right>)",
    },
    {
        "source": "left \\/ right",
        "parser": "_parse_or folds left-associatively",
        "ir": "BinaryExpr('\\/') with Boolean operands",
        "python": "(<left> or <right>)",
    },
    {
        "source": "IF condition THEN yes ELSE no",
        "parser": "_parse_if creates IfExpr; branches recurse",
        "ir": "IfExpr with Boolean condition and equal branch types",
        "python": "(<yes> if <condition> else <no>)",
    },
)
_UNSUPPORTED_SYNTAX: tuple[dict[str, str], ...] = (
    {"source_family": "sets and set constructors", "reason": "no set value, AST node, or evaluator rule"},
    {"source_family": "quantifiers and CHOOSE", "reason": "no binder or finite-domain rule"},
    {"source_family": "functions, records, tuples, sequences, and EXCEPT", "reason": "only scalar int/bool values are represented"},
    {"source_family": "user-defined expression operators and recursion", "reason": "definitions are not expression-callable"},
    {"source_family": "temporal operators, fairness, and liveness", "reason": "the explorer evaluates reached-state predicates only"},
    {"source_family": "ACTION/temporal stuttering forms and ENABLED", "reason": "not part of the action grammar"},
    {"source_family": "module instantiation and imported semantics", "reason": "EXTENDS is framing only in this fragment"},
)


def syntax_contract() -> dict[str, object]:
    """Return the complete accepted-form map for this restricted compiler.

    The returned data is deliberately serialisable and has no executable
    Python.  It is intended for the manuscript, API-adjacent tooling, and
    deterministic evidence bundles, where it prevents a reader from treating
    this implementation as a parser for the full TLA+ language.
    """
    return {
        "id": SYNTAX_CONTRACT_ID,
        "scope": "Every accepted source form is listed; forms outside this map are not supported.",
        "accepted_forms": [dict(form) for form in _SYNTAX_FORMS],
        "unsupported_families": [dict(family) for family in _UNSUPPORTED_SYNTAX],
    }


@dataclass(frozen=True)
class LiteralExpr:
    value: Value


@dataclass(frozen=True)
class VariableExpr:
    name: str


@dataclass(frozen=True)
class UnaryExpr:
    operator: str
    operand: "Expression"


@dataclass(frozen=True)
class BinaryExpr:
    operator: str
    left: "Expression"
    right: "Expression"


@dataclass(frozen=True)
class IfExpr:
    condition: "Expression"
    when_true: "Expression"
    when_false: "Expression"


Expression: TypeAlias = LiteralExpr | VariableExpr | UnaryExpr | BinaryExpr | IfExpr


@dataclass(frozen=True)
class ActionIR:
    name: str
    guards: tuple[Expression, ...]
    updates: Mapping[str, Expression]


@dataclass(frozen=True)
class ModelIR:
    variables: tuple[str, ...]
    variable_types: Mapping[str, TypeName]
    initial_state: Mapping[str, Value]
    actions: tuple[ActionIR, ...]
    next_actions: tuple[str, ...]


@dataclass(frozen=True)
class CompilationResult:
    """Stable artefacts produced by the restricted compiler pipeline.

    ``model`` is the executable semantic IR.  ``python`` is a readable target
    artefact for inspection only; the verifier never evaluates it.
    """

    source: str
    model: ModelIR
    python: str


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str
    position: int


def _type_of_value(value: Value) -> TypeName:
    # bool is a subclass of int in Python, so exact checks are required.
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    raise TranslationError("Only Boolean and integer values are supported.")


def _tokenize(text: str) -> list[_Token]:
    """Tokenise the expression subset without delegating parsing to Python."""
    tokens: list[_Token] = []
    index = 0
    two_char = ("/\\", "\\/", "/=", "<=", ">=", "==")
    while index < len(text):
        character = text[index]
        if character.isspace():
            index += 1
            continue
        matched = next((operator for operator in two_char if text.startswith(operator, index)), None)
        if matched is not None:
            tokens.append(_Token("operator", matched, index))
            index += len(matched)
            continue
        if character in "()+-*%<>=~":
            tokens.append(_Token("operator", character, index))
            index += 1
            continue
        if character.isdigit():
            end = index + 1
            while end < len(text) and text[end].isdigit():
                end += 1
            tokens.append(_Token("integer", text[index:end], index))
            index = end
            continue
        match = _IDENT_RE.match(text, index)
        if match is not None:
            name = match.group(0)
            end = match.end()
            if end < len(text) and text[end] == "'":
                raise TranslationError("Primed variables are not permitted in expressions.")
            if name in {"IF", "THEN", "ELSE", "TRUE", "FALSE"}:
                tokens.append(_Token("keyword", name, index))
            else:
                tokens.append(_Token("name", name, index))
            index = end
            continue
        raise TranslationError(f"Unsupported expression character at column {index + 1}: {character!r}")
    tokens.append(_Token("eof", "", len(text)))
    return tokens


class _ExpressionParser:
    """Recursive-descent parser with the precedence printed in the paper."""

    def __init__(self, text: str, variables: Mapping[str, TypeName]):
        self._variables = variables
        self._tokens = _tokenize(text)
        self._index = 0

    def parse(self) -> Expression:
        expression = self._parse_if()
        if self._peek().kind != "eof":
            token = self._peek()
            raise TranslationError(f"Unexpected token {token.text!r} at column {token.position + 1}.")
        _infer_type(expression, self._variables)
        return expression

    def _peek(self) -> _Token:
        return self._tokens[self._index]

    def _accept(self, text: str) -> _Token | None:
        if self._peek().text == text:
            token = self._peek()
            self._index += 1
            return token
        return None

    def _expect(self, text: str) -> _Token:
        token = self._accept(text)
        if token is None:
            current = self._peek()
            raise TranslationError(
                f"Expected {text!r} at column {current.position + 1}, "
                f"found {current.text or 'end of expression'!r}."
            )
        return token

    def _parse_if(self) -> Expression:
        if self._accept("IF") is not None:
            condition = self._parse_or()
            self._expect("THEN")
            when_true = self._parse_if()
            self._expect("ELSE")
            when_false = self._parse_if()
            return IfExpr(condition, when_true, when_false)
        return self._parse_or()

    def _parse_or(self) -> Expression:
        expression = self._parse_and()
        while self._accept("\\/") is not None:
            expression = BinaryExpr("\\/", expression, self._parse_and())
        return expression

    def _parse_and(self) -> Expression:
        expression = self._parse_comparison()
        while self._accept("/\\") is not None:
            expression = BinaryExpr("/\\", expression, self._parse_comparison())
        return expression

    def _parse_comparison(self) -> Expression:
        expression = self._parse_additive()
        if self._peek().text in {"=", "/=", "<", "<=", ">", ">="}:
            operator = self._peek().text
            self._index += 1
            expression = BinaryExpr(operator, expression, self._parse_additive())
        return expression

    def _parse_additive(self) -> Expression:
        expression = self._parse_multiplicative()
        while self._peek().text in {"+", "-"}:
            operator = self._peek().text
            self._index += 1
            expression = BinaryExpr(operator, expression, self._parse_multiplicative())
        return expression

    def _parse_multiplicative(self) -> Expression:
        expression = self._parse_unary()
        while self._peek().text in {"*", "%"}:
            operator = self._peek().text
            self._index += 1
            expression = BinaryExpr(operator, expression, self._parse_unary())
        return expression

    def _parse_unary(self) -> Expression:
        if self._accept("~") is not None:
            return UnaryExpr("~", self._parse_unary())
        if self._accept("-") is not None:
            return UnaryExpr("-", self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> Expression:
        token = self._peek()
        if token.kind == "integer":
            self._index += 1
            return LiteralExpr(int(token.text))
        if token.text == "TRUE":
            self._index += 1
            return LiteralExpr(True)
        if token.text == "FALSE":
            self._index += 1
            return LiteralExpr(False)
        if token.kind == "name":
            self._index += 1
            if token.text not in self._variables:
                raise TranslationError(f"Unknown source variable: {token.text}")
            return VariableExpr(token.text)
        if self._accept("(") is not None:
            expression = self._parse_if()
            self._expect(")")
            return expression
        raise TranslationError(f"Expected an expression at column {token.position + 1}.")


def _infer_type(expression: Expression, variable_types: Mapping[str, TypeName]) -> TypeName:
    if isinstance(expression, LiteralExpr):
        return _type_of_value(expression.value)
    if isinstance(expression, VariableExpr):
        return variable_types[expression.name]
    if isinstance(expression, UnaryExpr):
        inner = _infer_type(expression.operand, variable_types)
        if expression.operator == "~":
            if inner != "bool":
                raise TranslationError("The operator '~' requires a Boolean operand.")
            return "bool"
        if inner != "int":
            raise TranslationError("Unary '-' requires an integer operand.")
        return "int"
    if isinstance(expression, BinaryExpr):
        left = _infer_type(expression.left, variable_types)
        right = _infer_type(expression.right, variable_types)
        if expression.operator in {"+", "-", "*", "%"}:
            if left != "int" or right != "int":
                raise TranslationError(f"The operator {expression.operator!r} requires integer operands.")
            return "int"
        if expression.operator in {"/\\", "\\/"}:
            if left != "bool" or right != "bool":
                raise TranslationError(f"The operator {expression.operator!r} requires Boolean operands.")
            return "bool"
        if expression.operator in {"=", "/="}:
            if left != right:
                raise TranslationError("Equality compares values of the same declared type only.")
            return "bool"
        if left != "int" or right != "int":
            raise TranslationError(f"The operator {expression.operator!r} requires integer operands.")
        return "bool"
    if isinstance(expression, IfExpr):
        condition = _infer_type(expression.condition, variable_types)
        if condition != "bool":
            raise TranslationError("The IF condition must be Boolean.")
        yes_type = _infer_type(expression.when_true, variable_types)
        no_type = _infer_type(expression.when_false, variable_types)
        if yes_type != no_type:
            raise TranslationError("The THEN and ELSE expressions must have the same type.")
        return yes_type
    raise AssertionError(f"Unhandled expression type: {type(expression)!r}")


def parse_expression(text: str, variable_types: Mapping[str, TypeName]) -> Expression:
    if not isinstance(text, str) or not text.strip():
        raise TranslationError("Empty expression.")
    return _ExpressionParser(text, variable_types).parse()


def tokenize_expression(text: str) -> tuple[dict[str, int | str], ...]:
    """Return the expression token stream as an inspection artefact.

    The public form deliberately omits the end-of-file sentinel used by the
    recursive-descent parser.  Columns are one-based so that they agree with
    diagnostics shown to a user.
    """
    if not isinstance(text, str) or not text.strip():
        raise TranslationError("Empty expression.")
    return tuple(
        {"kind": token.kind, "text": token.text, "column": token.position + 1}
        for token in _tokenize(text)
        if token.kind != "eof"
    )


def expression_type(expression: Expression, variable_types: Mapping[str, TypeName]) -> TypeName:
    """Return the validated type of an AST expression."""
    return _infer_type(expression, variable_types)


def expression_to_tree(expression: Expression) -> dict[str, object]:
    """Serialise one typed AST expression without exposing Python objects.

    This representation is suitable for the compiler-inspection endpoint and
    evidence bundles.  It is a parse tree, not an alternative evaluator.
    """
    if isinstance(expression, LiteralExpr):
        return {"kind": "literal", "value": expression.value}
    if isinstance(expression, VariableExpr):
        return {"kind": "variable", "name": expression.name}
    if isinstance(expression, UnaryExpr):
        return {
            "kind": "unary",
            "operator": expression.operator,
            "operand": expression_to_tree(expression.operand),
        }
    if isinstance(expression, BinaryExpr):
        return {
            "kind": "binary",
            "operator": expression.operator,
            "left": expression_to_tree(expression.left),
            "right": expression_to_tree(expression.right),
        }
    if isinstance(expression, IfExpr):
        return {
            "kind": "if",
            "condition": expression_to_tree(expression.condition),
            "when_true": expression_to_tree(expression.when_true),
            "when_false": expression_to_tree(expression.when_false),
        }
    raise AssertionError(f"Unhandled expression type: {type(expression)!r}")


def evaluate_expression(expression: Expression, state: Mapping[str, Value]) -> Value:
    """Evaluate only the typed AST, never a user-provided Python string."""
    if isinstance(expression, LiteralExpr):
        return expression.value
    if isinstance(expression, VariableExpr):
        return state[expression.name]
    if isinstance(expression, UnaryExpr):
        value = evaluate_expression(expression.operand, state)
        return (not value) if expression.operator == "~" else -value  # type: ignore[operator]
    if isinstance(expression, BinaryExpr):
        if expression.operator == "/\\":
            return bool(evaluate_expression(expression.left, state)) and bool(evaluate_expression(expression.right, state))
        if expression.operator == "\\/":
            return bool(evaluate_expression(expression.left, state)) or bool(evaluate_expression(expression.right, state))
        left = evaluate_expression(expression.left, state)
        right = evaluate_expression(expression.right, state)
        if expression.operator == "+":
            return left + right  # type: ignore[operator]
        if expression.operator == "-":
            return left - right  # type: ignore[operator]
        if expression.operator == "*":
            return left * right  # type: ignore[operator]
        if expression.operator == "%":
            return left % right  # type: ignore[operator]
        if expression.operator == "=":
            return left == right
        if expression.operator == "/=":
            return left != right
        if expression.operator == "<":
            return left < right  # type: ignore[operator]
        if expression.operator == "<=":
            return left <= right  # type: ignore[operator]
        if expression.operator == ">":
            return left > right  # type: ignore[operator]
        if expression.operator == ">=":
            return left >= right  # type: ignore[operator]
        raise AssertionError(f"Unhandled binary operator: {expression.operator}")
    if isinstance(expression, IfExpr):
        branch = expression.when_true if evaluate_expression(expression.condition, state) else expression.when_false
        return evaluate_expression(branch, state)
    raise AssertionError(f"Unhandled expression type: {type(expression)!r}")


def render_expression(expression: Expression) -> str:
    """Render a typed source expression as readable Python source."""
    if isinstance(expression, LiteralExpr):
        return repr(expression.value)
    if isinstance(expression, VariableExpr):
        return f"state[{expression.name!r}]"
    if isinstance(expression, UnaryExpr):
        if expression.operator == "~":
            return f"(not {render_expression(expression.operand)})"
        return f"(-{render_expression(expression.operand)})"
    if isinstance(expression, BinaryExpr):
        operator = {"/\\": "and", "\\/": "or", "=": "==", "/=": "!="}.get(expression.operator, expression.operator)
        return f"({render_expression(expression.left)} {operator} {render_expression(expression.right)})"
    if isinstance(expression, IfExpr):
        return (
            f"({render_expression(expression.when_true)} if {render_expression(expression.condition)} "
            f"else {render_expression(expression.when_false)})"
        )
    raise AssertionError(f"Unhandled expression type: {type(expression)!r}")


def _without_comments(source: str) -> list[str]:
    return [line.split("\\*", 1)[0].rstrip() for line in source.splitlines()]


def _get_vars(source: str) -> list[str]:
    declarations = []
    for raw in _without_comments(source):
        match = re.match(r"^\s*VARIABLES?\s+([^\n]+)$", raw)
        if match is not None:
            declarations.append(match.group(1))
    if len(declarations) != 1:
        raise TranslationError("Provide exactly one VARIABLE or VARIABLES declaration.")
    variables = [name.strip() for name in declarations[0].split(",")]
    if not variables or any(not re.fullmatch(IDENT, name) for name in variables):
        raise TranslationError("Expected comma-separated variable names in VARIABLES.")
    reserved = sorted(name for name in variables if name in _RESERVED_IDENTIFIERS)
    if reserved:
        raise TranslationError(f"Variable names cannot use reserved words: {', '.join(reserved)}.")
    if len(set(variables)) != len(variables):
        raise TranslationError("Variable names must be unique.")
    return variables


def _blocks(source: str) -> dict[str, str]:
    definitions: dict[str, str] = {}
    current: str | None = None
    for raw in _without_comments(source):
        line = raw.strip()
        if not line or line.startswith("----") or line.startswith("====") or line.startswith("EXTENDS "):
            continue
        if re.match(r"^(VARIABLE|VARIABLES)\b", line):
            continue
        match = re.match(rf"^({IDENT})\s*==\s*(.*)$", line)
        if match is not None:
            current = match.group(1)
            if current in _RESERVED_IDENTIFIERS and current not in {"Init", "Next"}:
                raise TranslationError(f"Operator name cannot use reserved word: {current}.")
            if current in definitions:
                raise TranslationError(f"Duplicate operator definition: {current}")
            definitions[current] = match.group(2)
        elif current is not None:
            definitions[current] += "\n" + line
        else:
            raise TranslationError(f"Unsupported top-level statement: {line[:65]}")
    return definitions


def _split_action_clauses(block: str) -> list[str]:
    """Split only top-level action conjunctions.

    A conjunction inside parentheses or an IF condition remains part of the
    expression. At action level a top-level /\\ separates clauses. Boolean
    update expressions that use a top-level /\\ must therefore be parenthesised.
    """
    text = block.strip()
    if text.startswith("/\\"):
        text = text[2:].lstrip()
    pieces: list[str] = []
    start = 0
    index = 0
    parens = 0
    if_depth = 0
    while index < len(text):
        character = text[index]
        if character == "(":
            parens += 1
            index += 1
            continue
        if character == ")":
            parens -= 1
            if parens < 0:
                raise TranslationError("Unmatched ')' in an action or Init definition.")
            index += 1
            continue
        name = _IDENT_RE.match(text, index)
        if name is not None:
            word = name.group(0)
            if word == "IF":
                if_depth += 1
            elif word == "ELSE" and if_depth:
                if_depth -= 1
            index = name.end()
            continue
        if text.startswith("/\\", index) and parens == 0 and if_depth == 0:
            piece = text[start:index].strip()
            if not piece:
                raise TranslationError("Empty conjunction clause.")
            pieces.append(piece)
            start = index + 2
            index += 2
            continue
        index += 1
    if parens != 0:
        raise TranslationError("Unmatched '(' in an action or Init definition.")
    piece = text[start:].strip()
    if not piece:
        raise TranslationError("Empty conjunction clause.")
    pieces.append(piece)
    return pieces


def _parse_unchanged(clause: str, variables: tuple[str, ...], updates: dict[str, Expression]) -> bool:
    if not clause.startswith("UNCHANGED"):
        return False
    rest = clause[len("UNCHANGED") :].strip()
    if rest.startswith("<<") and rest.endswith(">>"):
        rest = rest[2:-2].strip()
    names = [name.strip() for name in rest.split(",") if name.strip()]
    if not names or any(name not in variables or name in updates for name in names):
        raise TranslationError("Invalid UNCHANGED variable list.")
    for name in names:
        updates[name] = VariableExpr(name)
    return True


def _parse_next(text: str, definitions: Mapping[str, str]) -> tuple[str, ...]:
    names = [part.strip() for part in re.split(r"\s*\\/\s*", text.strip())]
    if not names or any(not re.fullmatch(IDENT, name) for name in names):
        raise TranslationError("Next must be one action name or a disjunction of action names.")
    if any(name in _RESERVED_IDENTIFIERS or name not in definitions for name in names):
        raise TranslationError("Next must name defined actions only.")
    if len(set(names)) != len(names):
        raise TranslationError("Next must not repeat an action name.")
    return tuple(names)


def parse_tla(source: str) -> ModelIR:
    """Parse and type-check the documented source fragment into ModelIR."""
    if not isinstance(source, str) or not source.strip():
        raise TranslationError("Paste a TLA+ specification first.")
    if len(source.encode("utf-8")) > 200_000:
        raise TranslationError("Specification exceeds the 200 KB limit.")
    variables = tuple(_get_vars(source))
    definitions = _blocks(source)
    if "Init" not in definitions or "Next" not in definitions:
        raise TranslationError("This subset requires Init and Next definitions.")

    initial: dict[str, Value] = {}
    for clause in _split_action_clauses(definitions["Init"]):
        match = re.fullmatch(rf"({IDENT})\s*=\s*(-?\d+|TRUE|FALSE)", clause)
        if match is None or match.group(1) not in variables:
            raise TranslationError(f"Unsupported Init clause: {clause}")
        name, raw_value = match.groups()
        if name in initial:
            raise TranslationError(f"Duplicate Init assignment: {name}")
        initial[name] = True if raw_value == "TRUE" else False if raw_value == "FALSE" else int(raw_value)
    if set(initial) != set(variables):
        raise TranslationError("Init must assign every declared variable exactly once.")
    variable_types = {name: _type_of_value(initial[name]) for name in variables}
    next_actions = _parse_next(definitions["Next"], definitions)

    actions: list[ActionIR] = []
    for name in next_actions:
        guards: list[Expression] = []
        updates: dict[str, Expression] = {}
        for clause in _split_action_clauses(definitions[name]):
            assignment = re.fullmatch(rf"({IDENT})'\s*=\s*(.+)", clause, re.S)
            if assignment is not None:
                variable, expression_text = assignment.groups()
                if variable not in variables:
                    raise TranslationError(f"Unknown next-state variable: {variable}")
                if variable in updates:
                    raise TranslationError(f"Multiple next-state assignments to {variable} in {name}.")
                expression = parse_expression(expression_text, variable_types)
                if _infer_type(expression, variable_types) != variable_types[variable]:
                    raise TranslationError(f"The update of {variable} must preserve its declared {variable_types[variable]} type.")
                updates[variable] = expression
                continue
            if _parse_unchanged(clause, variables, updates):
                continue
            guard = parse_expression(clause, variable_types)
            if _infer_type(guard, variable_types) != "bool":
                raise TranslationError(f"Action guard in {name} must be Boolean.")
            guards.append(guard)
        if set(updates) != set(variables):
            missing = ", ".join(name for name in variables if name not in updates)
            raise TranslationError(f"Action {name} must assign or preserve every variable; missing: {missing}.")
        actions.append(ActionIR(name, tuple(guards), dict(updates)))
    return ModelIR(variables, variable_types, dict(initial), tuple(actions), next_actions)


def successors(model: ModelIR, state: Mapping[str, Value]) -> list[tuple[str, dict[str, Value]]]:
    """Evaluate enabled actions against the old state and return labelled successors."""
    transitions: list[tuple[str, dict[str, Value]]] = []
    for action in model.actions:
        if all(bool(evaluate_expression(guard, state)) for guard in action.guards):
            updated = dict(state)
            for variable in model.variables:
                updated[variable] = evaluate_expression(action.updates[variable], state)
            transitions.append((action.name, updated))
    return transitions


def canonical_state_key(model: ModelIR, state: Mapping[str, Value]) -> tuple[tuple[str, TypeName, Value], ...]:
    """Keep Boolean and integer values distinct even though Python equates True and 1."""
    key: list[tuple[str, TypeName, Value]] = []
    for variable in model.variables:
        value = state[variable]
        actual = _type_of_value(value)
        expected = model.variable_types[variable]
        if actual != expected:
            raise TranslationError(f"State value for {variable} has type {actual}; expected {expected}.")
        key.append((variable, actual, value))
    return tuple(key)


def model_to_tree(model: ModelIR) -> dict[str, object]:
    """Serialise the checked model IR and its embedded expression ASTs.

    The output makes compiler decisions inspectable in a web response or a
    deterministic evidence archive.  It intentionally contains no executable
    Python source and does not replace the typed ``ModelIR`` used internally.
    """
    return {
        "kind": "model",
        "variables": [
            {
                "name": variable,
                "type": model.variable_types[variable],
                "initial": model.initial_state[variable],
            }
            for variable in model.variables
        ],
        "actions": [
            {
                "name": action.name,
                "guards": [expression_to_tree(guard) for guard in action.guards],
                "updates": {
                    variable: expression_to_tree(action.updates[variable])
                    for variable in model.variables
                },
            }
            for action in model.actions
        ],
        "next_actions": list(model.next_actions),
    }


def model_to_python(model: ModelIR) -> str:
    """Render readable Python. The web verifier does not execute this text."""
    lines = [
        '"""Readable Python rendering of a restricted TLA+ model.',
        "",
        "This file is generated for inspection. The web verifier evaluates the typed",
        "source IR directly and does not execute generated text in its process.",
        '"""',
        f"INITIAL_STATE = {dict(model.initial_state)!r}",
        "",
        "def next_states(state):",
        "    return [successor for _action, successor in next_transitions(state)]",
        "",
        "def next_transitions(state):",
        "    transitions = []",
    ]
    for action in model.actions:
        condition = " and ".join(f"({render_expression(guard)})" for guard in action.guards) or "True"
        lines.extend([f"    # Action: {action.name}", f"    if {condition}:", "        updated = dict(state)"])
        for variable in model.variables:
            lines.append(f"        updated[{variable!r}] = {render_expression(action.updates[variable])}")
        lines.append(f"        transitions.append(({action.name!r}, updated))")
    lines.extend(["    return transitions", ""])
    output = "\n".join(lines)
    # Syntax validation is safe: compile does not execute the generated source.
    compile(output, "<generated_tla_python>", "exec")
    return output


def tla_to_python_from_string(source: str) -> str:
    """Compatibility entry point used by the HTTP API and evidence driver."""
    return compile_tla(source).python


def compile_tla(source: str) -> CompilationResult:
    """Run collection, parsing, type checking, IR lowering, and code emission.

    Keeping this explicit entry point is useful both for the application and
    for experiments: clients can inspect the source-to-IR boundary without
    confusing the generated Python with the verification semantics.
    """
    model = parse_tla(source)
    return CompilationResult(source=source, model=model, python=model_to_python(model))
