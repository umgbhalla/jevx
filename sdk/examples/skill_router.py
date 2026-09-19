"""Skill router: pick at most one skill per step, or nothing.

Two-stage for big catalogs: wide Choice over all skills + gate Nouls, then
reread top-3 with full descriptions + per-candidate fits Nouls. Declining is
a choice (abstain), never inferred from low confidence.
"""

from __future__ import annotations

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.py import Questions
from jevx.py import ask
from jevx.py import feels
from jevx.py import pick


class Gates(Questions):
    acts: bool = ask("must the assistant act on files/accounts/services, not just explain?")
    procedure: bool = ask("would an expert consult a documented procedure?")
    prose_ok: bool = ask("could a generalist satisfy this in prose with no tools?")


@ensure(lambda *a, result=None, **k: "skill" in result, msg="route returns skill key")
def route(
    request: str,
    skills: list[dict],
    backend: Backend | None = None,
    shortlist: int = 3,
    fits_at: float = 0.30,
) -> dict:
    """skills: [{name, description, full?}]. Returns {skill} or {skill: None}."""
    s1 = (backend or Live()).s1()
    if not 1 <= shortlist <= 10:
        raise ValueError("shortlist must be 1..10")
    try:
        return _route_inner(request, skills, s1, shortlist, fits_at)
    except Exception as e:
        return {"skill": None, "why": f"S1 error: {e}"}


def _route_inner(request, skills, s1, shortlist, fits_at) -> dict:
    wide = pick(
        "which skill, if any, should load for this request?",
        {"request": request},
        {s["name"]: s["description"] for s in skills},
        client=s1,
    )
    g = Gates(client=s1)({"request": request})  # 1 request
    if (g.acts is False or g.procedure is False) and g.prose_ok:
        return {"skill": None, "why": "gates closed"}
    top = sorted(wide.probabilities.items(), key=lambda kv: -kv[1])[:shortlist]
    by_name = {s["name"]: s for s in skills}
    detail = {n: f"{by_name[n]['description']}\n{by_name[n].get('full', '')}" for n, _ in top}
    detail["none"] = "No skill in the roster fits this request."
    second = pick(
        "exactly one skill is right — which? Read what each does.",
        {"request": request},
        detail,
        client=s1,
    )
    fits = {"none": 1.0 - max(wide.probabilities.values())}
    for n, _ in top:
        fits[n] = float(
            feels(
                f"does skill '{n}' do the specific thing requested?",
                {"request": request, "skill": detail[n]},
                client=s1,
            )
        )
    best = max(fits, key=fits.get)
    if best == "none" or fits[best] < fits_at:
        return {"skill": None, "why": "no fit", "fits": fits}
    if second.choice != best:
        return {"skill": None, "why": "rerank disagrees", "fits": fits}
    return {"skill": best, "confidence": fits[best], "fits": fits}
