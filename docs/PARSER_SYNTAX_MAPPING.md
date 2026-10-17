# Parser and syntax mapping contract

This document describes the complete language accepted by the compiler in this
archive. It is not a grammar for full TLA+. A source form is accepted only if
it appears below and meets the stated static rule. The machine-readable copy is
`syntax_mapping.json` in every generated evidence report.

## Parsing pipeline

1. **Collection.** The compiler removes text after `\*` on each line, locates
   exactly one `VARIABLE` or `VARIABLES` declaration, and collects named
   `Name == body` definitions. Module framing and `EXTENDS` are accepted as
   framing text only; no module is imported.
2. **Structural parsing.** `Init` is split into top-level `/\` clauses. For an
   action, top-level `/\` separates guards, primed assignments, and
   `UNCHANGED` clauses. Parentheses and `IF ... THEN ... ELSE ...` protect an
   inner conjunction from this splitter. `Next` is split only at top-level
   `\/` and must name actions.
3. **Expression parsing.** The lexer returns tokens with one-based columns.
   Recursive-descent functions parse `IF`, `\/`, `/\`, comparisons, additive
   operators, multiplicative operators, unary operators, and primary values in
   that order. This gives the precedence shown in `main.tex`.
4. **Static checking.** Names must be declared variables; every guard and
   property must be Boolean; arithmetic is integer-only; equality needs equal
   types; conditional branches and assignments preserve a type; and every
   action provides one next value for each variable.
5. **Lowering and rendering.** The checked tree is stored in `ModelIR` and
   rendered as readable Python. The verifier evaluates the `ModelIR` directly;
   it does not execute the rendered Python.

## Structural source forms

| Source form | Parser action and tree/IR result | Python form |
|---|---|---|
| `\* comment` | Removes the rest of that line. | None. |
| `---- MODULE M ----`, `EXTENDS N`, `====` | Accepted as framing only. `EXTENDS` does not import semantics. | None. |
| `VARIABLE x` or `VARIABLES x, y` | Records ordered, unique, non-reserved scalar names in `ModelIR.variables`. | Dictionary keys and `state['x']` reads. |
| `Name == body` | Collects one top-level definition. `Init`, actions named in `Next`, and `Next` have distinct later rules. | Depends on the definition role. |
| `Init == x = 0 /\ b = TRUE` | Requires exactly one literal assignment for every variable; stores exact `int`/`bool` types. | `INITIAL_STATE = {'x': 0, 'b': True}`. |
| `Step == Clause /\ Clause` | Splits only top-level conjunctions into one `ActionIR`. | One labelled `if` block. |
| Guard `x < 3` | Parses a Boolean expression and adds its AST to `ActionIR.guards`. | Condition in `if (...)`. |
| `x' = Expr` | Primed names are valid only here; adds a typed expression to `ActionIR.updates['x']`. | `updated['x'] = <expression>`. |
| `UNCHANGED x`, `UNCHANGED x, y`, or `UNCHANGED <<x, y>>` | Adds `VariableExpr(x)` for each listed variable. | `updated['x'] = state['x']`. |
| `Next == A \/ B` | Requires distinct defined action names and preserves their source order in `ModelIR.next_actions`. | Ordered action blocks append `('A', updated)` and `('B', updated)`. |

## Expression forms and exact lowering

| TLA+ source | AST node and static rule | Python rendering |
|---|---|---|
| `42` | `LiteralExpr(42)`, type `int`. | `42` |
| `TRUE`, `FALSE` | `LiteralExpr(True/False)`, type `bool`. | `True`, `False` |
| `x` | `VariableExpr('x')`; `x` must be declared. | `state['x']` |
| `(Expr)` | Parses an enclosed expression and changes grouping. | Compound nodes are parenthesised. |
| `-Expr` | `UnaryExpr('-')`; operand must be `int`. | `(-<expression>)` |
| `~Expr` | `UnaryExpr('~')`; operand must be `bool`. | `(not <expression>)` |
| `a + b`, `a - b`, `a * b`, `a % b` | `BinaryExpr`; both operands must be `int`. `*` and `%` bind more tightly than `+` and `-`; each level is left-associative. | Same arithmetic operator in parenthesised Python. |
| `a = b`, `a /= b` | `BinaryExpr`; operands must have the same exact declared type. One comparison is allowed at this precedence level. | `a == b`, `a != b` |
| `a < b`, `a <= b`, `a > b`, `a >= b` | `BinaryExpr`; both operands must be `int`. | Same comparison operator. |
| `p /\ q` | `BinaryExpr('/\\')`; both operands must be `bool`; left-associative. | `(p and q)` |
| `p \/ q` | `BinaryExpr('\\/')`; both operands must be `bool`; left-associative. | `(p or q)` |
| `IF p THEN a ELSE b` | `IfExpr(p, a, b)`; `p` must be Boolean and both branches have the same type. Branches may contain another `IF`. | `(a if p else b)` |

The parser uses the precedence order: primary, unary, multiplication/remainder,
addition/subtraction, one comparison, conjunction, disjunction, and
conditional. A primed variable inside an expression is rejected so every
right-hand side reads the old state. In an action, an unparenthesised top-level
`/\` ends the current clause. A Boolean update expression that uses `/\` must
therefore be written in parentheses.

## Examples

```tla
VARIABLES x, done
Init == /\ x = 0
        /\ done = FALSE
Step == /\ x < 2 /\ ~done
        /\ x' = IF x = 0 THEN x + 1 ELSE -1
        /\ done' = (x = 1)
Next == Step
```

The update of `x` becomes the tree
`IfExpr(BinaryExpr('=', VariableExpr('x'), LiteralExpr(0)),
BinaryExpr('+', VariableExpr('x'), LiteralExpr(1)),
UnaryExpr('-', LiteralExpr(1)))` and the generated Python is:

```python
updated['x'] = ((state['x'] + 1) if (state['x'] == 0) else (-1))
```

Both updates evaluate against the old `state`; the assignment to `done` cannot
observe the new value of `x`.

## Explicitly unsupported full-language families

- Sets, set constructors, membership, and set operators.
- Quantifiers, `CHOOSE`, and bounded domains.
- Functions, records, tuples, sequences, and `EXCEPT`.
- User-defined expression operators, recursion, and parameterised operators.
- Temporal operators, fairness, liveness, stuttering forms, and `ENABLED`.
- Module instantiation or semantics imported through `EXTENDS`.

These forms are rejected or fall outside the structural contract. Their
presence must not be interpreted as a Python translation or a verification
result for full TLA+.
