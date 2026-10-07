import re


class GraphError(Exception):
    pass


def tokenize(text):
    return re.findall(r"[a-z0-9_]+", str(text).lower())


class CapabilityGraph:
    """DAG of tool capabilities. Edges carry a base weight and token weights; the routing
    matrix scores an edge against intent tokens. Plans touching unknown nodes, missing edges
    or sub-threshold edges are rejected before dispatch. Malformed graphs raise (fail closed)."""

    def __init__(self, tools, doc):
        try:
            self.nodes = set(tools)
            self.threshold = float(doc.get("threshold", 0.5))
            self.edges = {}
            for e in doc.get("edges", []):
                a, b = e["from"], e["to"]
                if a not in self.nodes or b not in self.nodes:
                    raise GraphError(f"edge references unknown node: {a}->{b}")
                if (a, b) in self.edges:
                    raise GraphError(f"duplicate edge: {a}->{b}")
                w = float(e.get("weight", 1.0))
                if not 0 <= w <= 1:
                    raise GraphError(f"edge weight out of range: {a}->{b}")
                toks = e.get("tokens", {})
                if isinstance(toks, list):
                    toks = {t: 1.0 for t in toks}
                self.edges[(a, b)] = (w, {str(t).lower(): float(v) for t, v in toks.items()})
        except (KeyError, TypeError, ValueError, AttributeError) as ex:
            raise GraphError(f"invalid graph: {ex}")
        self.out = {n: [] for n in self.nodes}
        for a, b in self.edges:
            self.out[a].append(b)
        self._check_acyclic()

    @classmethod
    def from_policy(cls, policy, doc):
        return cls(policy.tools, doc)

    def _check_acyclic(self):
        state = {}

        def visit(n):
            state[n] = 1
            for m in self.out[n]:
                if state.get(m) == 1:
                    raise GraphError(f"cycle detected at {n}->{m}")
                if m not in state:
                    visit(m)
            state[n] = 2

        for n in sorted(self.nodes):
            if n not in state:
                visit(n)

    def score(self, a, b, intent):
        """Routing-matrix entry: base weight scaled by the strongest matching intent token weight."""
        if (a, b) not in self.edges:
            return 0.0
        w, toks = self.edges[(a, b)]
        it = tokenize(intent)
        if not toks:
            return w
        if not it:
            return 0.0
        return w * max([toks.get(t, 0.0) for t in set(it)] + [0.0])

    def matrix(self, intent):
        return {k: self.score(k[0], k[1], intent) for k in self.edges}

    def validate_plan(self, plan, intent):
        """Return None if plan (list of node names) is routable, else a reason string."""
        if not plan:
            return "empty_plan"
        for n in plan:
            if n not in self.nodes:
                return f"unknown_node:{n}"
        if len(set(plan)) != len(plan):
            return "repeated_node"
        for a, b in zip(plan, plan[1:]):
            if (a, b) not in self.edges:
                return f"no_edge:{a}->{b}"
            if self.score(a, b, intent) < self.threshold:
                return f"low_score:{a}->{b}"
        return None

    def route(self, start, intent):
        """Highest-scoring path (product of edge scores) from start; edges below threshold are pruned."""
        if start not in self.nodes:
            raise GraphError(f"unknown node: {start}")
        m = self.matrix(intent)
        best = {}

        def walk(n):
            if n in best:
                return best[n]
            res = (1.0, [n])
            for c in sorted(self.out[n]):
                s = m[(n, c)]
                if s < self.threshold:
                    continue
                sub_s, sub_p = walk(c)
                cand = (s * sub_s, [n] + sub_p)
                if res[1] == [n] or cand[0] > res[0]:
                    res = cand
            best[n] = res
            return res

        return walk(start)[1]
