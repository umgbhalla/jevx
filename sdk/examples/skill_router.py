"""Skill router: pick at most one skill per step, or nothing.

Two-stage for big catalogs: wide Choice over all skills + gate Nouls, then
reread top-3 with full descriptions + per-candidate fits Nouls. Declining is
a choice (abstain), never inferred from low confidence.
"""

from __future__ import annotations

from typing import Any

from jevx.client import Client
from jevx.py import Questions, ask, feels, pick


class Gates(Questions):
    acts: bool = ask("must the assistant act on files/accounts/services, not just explain?")
    procedure: bool = ask("would an expert consult a documented procedure?")
    prose_ok: bool = ask("could a generalist satisfy this in prose with no tools?")


def route(request: str, skills: list[dict], s1: Client | None = None,
          shortlist: int = 3, gate_at: float = 0.30, fits_at: float = 0.30) -> dict:
    """skills: [{name, description, full?}]. Returns {skill} or {skill: None}."""
    wide = pick("which skill, if any, should load for this request?",
                {"request": request},
                {s["name"]: s["description"] for s in skills}, client=s1)
    g = Gates(client=s1)({"request": request})  # 1 request
    if (g.acts is False or g.procedure is False) and g.prose_ok:
        if max(wide.probabilities.values()) < gate_at:
            return {"skill": None, "why": "gates closed"}
    top = sorted(wide.probabilities.items(), key=lambda kv: -kv[1])[:shortlist]
    by_name = {s["name"]: s for s in skills}
    detail = {n: f"{by_name[n]['description']}\n{by_name[n].get('full', '')}" for n, _ in top}
    second = pick("exactly one skill is right — which? Read what each does.",
                  {"request": request}, detail, client=s1)
    fits = {}
    for n, _ in top:
        fits[n] = float(feels(f"does skill '{n}' do the specific thing requested?",
                              {"request": request, "skill": detail[n]}, client=s1))
    best = max(fits, key=fits.get)
    if fits[best] < fits_at:
        return {"skill": None, "why": "no fit", "fits": fits}
    if second.choice != best and fits[second.choice] < fits_at:
        return {"skill": None, "why": "no fit", "fits": fits}
    return {"skill": best, "confidence": fits[best], "fits": fits}
