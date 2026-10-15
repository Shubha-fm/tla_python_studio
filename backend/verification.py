"""Bounded explicit-state exploration. Not TLC or an unbounded proof."""
import ast
from collections import deque
from tla_parser import tla_to_python_from_string, _expression, _get_vars, TranslationError

ALLOWED=(ast.Expression,ast.BoolOp,ast.BinOp,ast.UnaryOp,ast.Compare,ast.Load,ast.Name,ast.Subscript,ast.Constant,ast.And,ast.Or,ast.Not,ast.Add,ast.Sub,ast.Mult,ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE,ast.USub)

def safe_eval(expr,state):
    tree=ast.parse(expr,mode='eval')
    if any(not isinstance(node,ALLOWED) for node in ast.walk(tree)):
        raise TranslationError('Unsupported property expression')
    return eval(compile(tree,'<property>','eval'),{'__builtins__':{}},{'state':state})

def verify(source,property_text='',max_depth=12,max_states=120):
    if type(max_depth)!=int or not 0<=max_depth<=40:
        raise TranslationError('max_depth must be 0–40.')
    if type(max_states)!=int or not 1<=max_states<=500:
        raise TranslationError('max_states must be 1–500.')
    generated=tla_to_python_from_string(source)
    namespace={'__builtins__':{'dict':dict,'list':list}}
    exec(compile(generated.split('def explore(')[0],'<translated>','exec'),namespace)
    initial=namespace['INITIAL_STATE']; next_states=namespace['next_states']
    variables=_get_vars(source);prop=property_text.strip()
    compiled=_expression(prop,variables) if prop else None
    nodes=[{'id':0,'state':initial,'depth':0}];edges=[]
    key=lambda s:tuple((v,s[v]) for v in variables)
    visited={key(initial):0};parent={0:None};queue=deque([0])
    cutoff=False;violations=[];deadlocks=[]
    while queue:
        id=queue.popleft();node=nodes[id];state=node['state']
        if compiled is not None and not bool(safe_eval(compiled,state)):
            violations.append(id)
        successors=next_states(state)
        if node['depth']>=max_depth:
            if successors:cutoff=True
            else:deadlocks.append(id)
            continue
        if not successors:deadlocks.append(id)
        for successor in successors:
            ident=key(successor)
            if ident not in visited:
                if len(nodes)>=max_states:
                    cutoff=True;continue
                target=len(nodes);visited[ident]=target;parent[target]=id
                nodes.append({'id':target,'state':successor,'depth':node['depth']+1})
                queue.append(target)
            else:target=visited[ident]
            edges.append({'source':id,'target':target})
    def trace(id):
        route=[]
        while id is not None:
            route.append(id);id=parent[id]
        return list(reversed(route))
    return {'nodes':nodes,'edges':edges,'summary':{'states':len(nodes),'transitions':len(edges),'max_depth':max_depth,'max_states':max_states,'truncated':cutoff,'deadlocks':len(deadlocks),'property':prop,'property_status':('not_checked' if not prop else 'violation' if violations else 'bounded_pass' if cutoff else 'pass_finite_graph')},'counterexample':trace(violations[0]) if violations else [],'deadlock_trace':trace(deadlocks[0]) if deadlocks else [],'disclaimer':'Bounded exploration of a restricted TLA+ subset, not TLC. A bounded pass is not a general proof.'}
