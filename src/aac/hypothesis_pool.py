"""HypothesisPool — MEC enumeration over a GIVEN skeleton (AGDE-1 packet §3; pure stdlib).

A hypothesis is a DAG orientation of the given undirected skeleton, represented as a parent map
tuple(frozenset) for hashability/determinism. The pool handed to every arm is the Markov equivalence
class of the true DAG (same skeleton + same v-structures, Verma-Pearl): observational data cannot
discriminate within it (identifiability theorem), so the gate isolates ORIENTATION-BY-INTERVENTION."""
from __future__ import annotations

from itertools import product


def orient(skeleton: list[tuple[int, int]], bits: tuple[int, ...]) -> dict[int, frozenset[int]]:
    """bits[e]==0 orients edge (a,b) as a->b, ==1 as b->a. Returns child->parents map."""
    pa: dict[int, set[int]] = {}
    for (a, b), bit in zip(skeleton, bits):
        src, dst = (a, b) if bit == 0 else (b, a)
        pa.setdefault(dst, set()).add(src)
    return {k: frozenset(v) for k, v in pa.items()}


def is_acyclic(n: int, pa: dict[int, frozenset[int]]) -> bool:
    state = [0] * n  # 0=unseen 1=visiting 2=done

    def visit(u: int) -> bool:
        if state[u] == 1:
            return False
        if state[u] == 2:
            return True
        state[u] = 1
        for p in pa.get(u, ()):  # edge p->u; walk parents (any orientation works for cycle check)
            if not visit(p):
                return False
        state[u] = 2
        return True

    return all(visit(u) for u in range(n))


def v_structures(n: int, pa: dict[int, frozenset[int]], skeleton_adj: set[frozenset[int]]) -> frozenset:
    """Immoralities: a->c<-b with a,b non-adjacent in the skeleton."""
    out = set()
    for c in range(n):
        ps = sorted(pa.get(c, ()))
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                a, b = ps[i], ps[j]
                if frozenset((a, b)) not in skeleton_adj:
                    out.add((a, c, b))
    return frozenset(out)


def canon(pa: dict[int, frozenset[int]]) -> tuple:
    return tuple(sorted((k, tuple(sorted(v))) for k, v in pa.items() if v))


def mec(n: int, skeleton: list[tuple[int, int]], true_pa: dict[int, frozenset[int]]) -> list[dict[int, frozenset[int]]]:
    """All acyclic orientations of the skeleton sharing the true DAG's v-structures (incl. truth itself),
    deterministically ordered by canonical form."""
    adj = {frozenset(e) for e in skeleton}
    target = v_structures(n, true_pa, adj)
    out = []
    for bits in product((0, 1), repeat=len(skeleton)):
        pa = orient(skeleton, bits)
        if is_acyclic(n, pa) and v_structures(n, pa, adj) == target:
            out.append(pa)
    out.sort(key=canon)
    return out
