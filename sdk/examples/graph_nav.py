"""Graph traversal: Choice over neighbors + Noul goal check per hop, beam search.

Ports: opaque eK edge keys + criteria dicts, prop hygiene (drop lists/vectors,
truncate, identity-first), per-type/total edge caps with round-robin, top_k +
cutoff branching, sum-log-prob beam scoring, visited anti-cycle, budget/depth
termination, FreeText/TargetNode/PathIntent goal modes. In-memory graph.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import field

from jevx.backends import Live
from jevx.contracts import ensure
from jevx.py import Questions
from jevx.py import ask
from jevx.py import pick

MAX_OPTS, PER_TYPE, TOTAL = 255, 10, 60
MAX_CHARS = 200


def clean_props(props: dict, identity: list[str] = []) -> dict:
    out = {}
    for k in identity + [k for k in props if k not in identity]:
        v = props.get(k)
        if isinstance(v, (list, dict)) or v is None:
            continue
        s = str(v)
        out[k] = s[:MAX_CHARS]
    return out


@dataclass
class Graph:
    nodes: dict[str, dict] = field(default_factory=dict)  # id -> {label, props}
    edges: dict[str, list[dict]] = field(default_factory=dict)  # src -> [{rel, props, dst}]

    def neighbors(self, src: str) -> list[dict]:
        by_type: dict[str, list[dict]] = {}
        for e in self.edges.get(src, []):
            by_type.setdefault(e["rel"], []).append(e)
        out = []
        for rel in sorted(by_type):
            out.extend(by_type[rel][:PER_TYPE])
            if len(out) >= TOTAL:
                break
        return out[:TOTAL]


class Hop(Questions):
    reached: bool = ask("has the goal been reached at the current node?", threshold=0.5)


def one_hop(g: Graph, node: str, goal: dict, s1) -> tuple[list[tuple[float, dict]], bool]:
    nbrs = g.neighbors(node)[:MAX_OPTS]
    n = g.nodes[node]
    state = {
        "current_node": {
            "id": node,
            "label": n["label"],
            "props": clean_props(n.get("props", {}), n.get("identity", [])),
        },
        "goal": goal,
    }
    if not nbrs:
        r = Hop(client=s1)({"state": state, "edges": []})
        return [], bool(r.reached)
    keys, crit = [], {}
    for i, e in enumerate(nbrs):
        k = f"e{i}"
        keys.append((k, e))
        t = g.nodes[e["dst"]]
        crit[k] = (
            f"{e['rel']} -> {t['label']} {clean_props(t.get('props', {}), t.get('identity', []))}"
        )
    c = pick(
        f"Choose the single outgoing relationship advancing this goal: {goal['description']}",
        {**state, " hop": len(keys)},
        crit,
        client=s1,
    )
    order = sorted(c.probabilities.items(), key=lambda kv: -kv[1])
    by_key = {k: e for k, e in keys}
    branches = [(p, by_key[k]) for k, p in order if k in by_key]  # drop off-list keys
    r = Hop(client=s1)({**state, "picked": c.choice})
    return branches, bool(r.reached)


@ensure(
    lambda *a, result=None, **k: (
        result["status"] in ("GOAL_REACHED", "NO_CANDIDATES", "BUDGET_EXHAUSTED", "MAX_DEPTH")
    ),
    msg="known nav status",
)
def navigate(
    g: Graph,
    start: str,
    goal: dict,
    backend=None,
    max_depth: int = 4,
    max_calls: int = 24,
    top_k: int = 2,
    cutoff: float = 0.05,
    beam: int = 4,
    length_norm: bool = False,
) -> dict:
    """Beam search over (node, path, cum_log_prob, visited, depth)."""
    s1 = (backend or Live()).s1()
    frontier = [{"node": start, "path": [start], "score": 0.0, "visited": {start}, "depth": 0}]
    calls = 0
    target = goal.get("target_id")

    def key(b):
        return b["score"] / len(b["path"]) if length_norm else b["score"]

    while frontier and calls < max_calls:
        nxt = []
        for b in frontier:
            if target and b["node"] == target:
                return {"status": "GOAL_REACHED", "path": b["path"], "calls": calls}
            if b["depth"] >= max_depth:
                continue
            branches, reached = one_hop(g, b["node"], goal, s1)
            calls += 1
            for p, e in branches:
                if target and e["dst"] == target:
                    return {
                        "status": "GOAL_REACHED",
                        "path": b["path"] + [e["dst"]],
                        "calls": calls,
                    }
            if reached and goal.get("mode") != "target":
                return {"status": "GOAL_REACHED", "path": b["path"], "calls": calls}
            if not branches:
                continue
            take = [x for x in branches if x[0] >= cutoff][:top_k] or branches[:1]
            for p, e in take:
                dst = e["dst"]
                if dst in b["visited"]:
                    continue
                nxt.append(
                    {
                        "node": dst,
                        "path": b["path"] + [dst],
                        "score": b["score"] + math.log(max(p, 1e-12)),
                        "visited": b["visited"] | {dst},
                        "depth": b["depth"] + 1,
                    }
                )
        if not nxt:
            return {"status": "NO_CANDIDATES", "best": frontier[0]["path"], "calls": calls}
        frontier = sorted(nxt, key=key, reverse=True)[:beam]
    best = max(frontier, key=key) if frontier else None
    reason = "BUDGET_EXHAUSTED" if calls >= max_calls else "MAX_DEPTH"
    return {"status": reason, "best": best["path"] if best else [], "calls": calls}


def demo_graph() -> Graph:
    g = Graph()
    for nid, label, props in [
        ("acme", "Company", {"name": "Acme", "ein": "1"}),
        ("inv1", "Invoice", {"no": "A1", "total": 110}),
        ("inv2", "Invoice", {"no": "A2", "total": 90}),
        ("po7", "PO", {"no": "PO-7"}),
        ("amy", "Approver", {"name": "Amy"}),
    ]:
        g.nodes[nid] = {"label": label, "props": props, "identity": ["name", "no"]}
    g.edges = {
        "acme": [
            {"rel": "BILLED", "props": {}, "dst": "inv1"},
            {"rel": "BILLED", "props": {}, "dst": "inv2"},
            {"rel": "ISSUED", "props": {}, "dst": "po7"},
        ],
        "inv1": [{"rel": "MATCHES", "props": {}, "dst": "po7"}],
        "po7": [{"rel": "APPROVED_BY", "props": {}, "dst": "amy"}],
        "inv2": [],
        "amy": [],
    }
    return g
