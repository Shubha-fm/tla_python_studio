"""Translator for a deliberately limited subset of TLA+."""
import ast
import re

class TranslationError(ValueError):
    pass

IDENT = r'[A-Za-z_][A-Za-z_0-9]*'

def _clauses(block):
    block = re.sub(r'^\s*/\\\s*', '', block.strip())
    return [p.strip() for p in re.split(r'\s*/\\\s*', block) if p.strip()]

def _expression(s, variables, next_state=False):
    s = s.strip()
    if not s:
        raise TranslationError('Empty expression')
    tok = re.compile(r"\s*(?:(\d+)|([A-Za-z_]\w*'?)|(/=|<=|>=|=|[()+*<>-]))")
    tokens = []
    pos = 0
    while pos < len(s):
        if not s[pos:].strip():
            break
        match = tok.match(s, pos)
        if not match:
            raise TranslationError(f'Unsupported expression near: {s[pos:pos+30]!r}')
        val = match.group(0).strip()
        pos = match.end()
        if val in ('TRUE', 'FALSE'):
            tokens.append(val.title())
        elif val in ('=', '/='):
            tokens.append('==' if val == '=' else '!=')
        elif re.fullmatch(IDENT + "'", val):
            name = val[:-1]
            if not next_state or name not in variables:
                raise TranslationError(f'Unexpected primed variable: {val}')
            tokens.append(f"updated[{name!r}]")
        elif val in variables:
            tokens.append(f"state[{val!r}]")
        elif re.fullmatch(IDENT, val):
            raise TranslationError(f'Unknown symbol or operator: {val}')
        else:
            tokens.append(val)
    out = ' '.join(tokens)
    try:
        tree = ast.parse(out, mode='eval')
    except SyntaxError as exc:
        raise TranslationError(f'Invalid expression: {s}') from exc
    allowed = (ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare,
               ast.Load, ast.Subscript, ast.Name, ast.Constant, ast.And, ast.Or,
               ast.Not, ast.Add, ast.Sub, ast.Mult, ast.Eq, ast.NotEq, ast.Lt,
               ast.LtE, ast.Gt, ast.GtE, ast.USub)
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise TranslationError('Unsupported expression syntax')
    return out

def _blocks(src):
    definitions = {}
    current = None
    for raw in src.splitlines():
        line = raw.split('\\*', 1)[0].strip()
        if not line or line.startswith('----') or line.startswith('====') or line.startswith('EXTENDS '):
            continue
        if re.match(r'^(VARIABLE|VARIABLES)\b', line):
            continue
        m = re.match(rf'^({IDENT})\s*==\s*(.*)$', line)
        if m:
            current = m.group(1)
            definitions[current] = m.group(2)
        elif current:
            definitions[current] += '\n' + line
        else:
            raise TranslationError(f'Unsupported top-level statement: {line[:65]}')
    return definitions

def _get_vars(src):
    m = re.search(r'^\s*VARIABLES?\s+([^\n]+)', src, re.M)
    if not m:
        raise TranslationError('Add a VARIABLES declaration.')
    raw = [v.strip() for v in m.group(1).split(',')]
    if not raw or any(not re.fullmatch(IDENT, v) for v in raw) or len(set(raw)) != len(raw):
        raise TranslationError('Expected comma-separated variable names in VARIABLES.')
    return raw

def tla_to_python_from_string(src):
    if not isinstance(src, str) or not src.strip():
        raise TranslationError('Paste a TLA+ specification first.')
    if len(src) > 200000:
        raise TranslationError('Specification exceeds the 200 KB limit.')
    vars_ = _get_vars(src)
    defs = _blocks(src)
    if 'Init' not in defs or 'Next' not in defs:
        raise TranslationError('This subset requires Init and Next definitions.')
    init = {}
    for clause in _clauses(defs['Init']):
        m = re.fullmatch(rf'({IDENT})\s*=\s*(-?\d+|TRUE|FALSE)', clause)
        if not m or m.group(1) not in vars_:
            raise TranslationError(f'Unsupported Init clause: {clause}')
        var, val = m.groups()
        if var in init:
            raise TranslationError(f'Duplicate Init assignment: {var}')
        init[var] = True if val == 'TRUE' else False if val == 'FALSE' else int(val)
    if set(init) != set(vars_):
        raise TranslationError('Init must assign every variable once.')
    nxt = defs['Next'].strip()
    if '\\/' in nxt:
        items = [x.strip() for x in re.split(r'\s*\\/\s*', nxt) if x.strip()]
        if not all(re.fullmatch(IDENT, x) and x in defs for x in items):
            raise TranslationError('Next disjunction must contain defined action names only.')
        actions = [(x, defs[x]) for x in items]
    elif re.fullmatch(IDENT, nxt) and nxt in defs:
        actions = [(nxt, defs[nxt])]
    else:
        actions = [('Next', nxt)]
    compiled = []
    for name, body in actions:
        guards = []
        updates = {}
        for clause in _clauses(body):
            m = re.fullmatch(rf"({IDENT})'\s*=\s*(.+)", clause, re.S)
            if m:
                var, expression = m.groups()
                if var not in vars_:
                    raise TranslationError(f'Unknown next-state variable: {var}')
                if var in updates:
                    raise TranslationError(f'Multiple assignments to {var} in {name}')
                if "'" in expression:
                    raise TranslationError('Primed right-hand-side variables are unsupported.')
                updates[var] = _expression(expression, vars_)
            else:
                if 'UNCHANGED' in clause:
                    raise TranslationError('UNCHANGED is not supported. Assign every variable.')
                guards.append(_expression(clause, vars_))
        if set(updates) != set(vars_):
            raise TranslationError(f'Action {name} must assign all variables.')
        compiled.append((name, guards, updates))
    result = ['"""Restricted TLA+ translation, not a refinement proof or TLC replacement."""',
              f'INITIAL_STATE = {repr(init)}', '', 'def next_states(state):',
              '    successors = []']
    for name, guards, updates in compiled:
        cond = ' and '.join(f'({x})' for x in guards) or 'True'
        result.extend([f'    # Action: {name}', f'    if {cond}:', '        updated = dict(state)'])
        for v, expr in updates.items():
            result.append(f'        updated[{v!r}] = {expr}')
        result.append('        successors.append(updated)')
    result.extend(['    return successors', '', 'def explore(max_depth=5):',
                   '    frontier = [INITIAL_STATE]', '    seen = set()',
                   '    for depth in range(max_depth + 1):', '        upcoming = []',
                   '        for state in frontier:', '            key = tuple(sorted(state.items()))',
                   '            if key in seen:', '                continue', '            seen.add(key)',
                   '            print(f"depth={depth}: {state}")',
                   '            if depth < max_depth:', '                upcoming.extend(next_states(state))',
                   '        frontier = upcoming', '    return len(seen)', '',
                   'if __name__ == "__main__":', '    explore()', ''])
    output = '\n'.join(result)
    compile(output, '<generated>', 'exec')
    return output
