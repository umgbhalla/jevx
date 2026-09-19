"""MCP firewall: screen tool calls, results, and descriptions semantically.

Every tool invocation passes a 3-Noul battery (malicious? exfiltrating?
destructive?) plus a severity Score. Blocked calls never execute; blocked
results never reach the model. Allowlisted read-only tools skip free.
"""

from __future__ import annotations

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.py import case
from jevx.py import noul
from jevx.py import score
from jevx.py import vector

READ_ONLY = {"read", "glob", "grep", "list", "describe", "search"}


SCREEN = vector(
    malicious=noul("does this tool call or result serve an attacker's goal?"),
    exfiltrating=noul("does this move secrets or private data outward?"),
    destructive=noul("does this destroy data or change external state?"),
    severity=score("worst-case severity?", ("harmless", "suspicious", "dangerous")),
)


@ensure(
    lambda *a, result=None, **k: (
        result is not None and result["verdict"] in ("allow", "block", "review")
    ),
    msg="known shield verdict",
)
def screen_call(tool: str, args: dict, backend: Backend | None = None) -> dict:
    if tool in READ_ONLY:
        return {"verdict": "allow", "why": "read-only allowlist", "requests": 0}
    s1 = (backend or Live()).s1()
    s = SCREEN.ask({"tool": tool, "args": args}, client=s1)  # 1 request
    severity = float(s.severity)
    verdict, why = case[
        s.malicious >= 0.70 or s.exfiltrating >= 0.70 : ("block", "malicious/exfiltrating"),
        s.destructive >= 0.70 and severity >= 1.5 : ("block", "destructive"),
        s.destructive >= 0.70 or severity >= 1.0 : ("review", None),
        ... : ("allow", None),
    ].ask({})
    return {"verdict": verdict, "severity": severity, **({"why": why} if why else {})}


@ensure(
    lambda *a, result=None, **k: (
        result is not None and result["verdict"] in ("allow", "block", "review")
    ),
    msg="known shield verdict",
)
def screen_result(tool: str, result_text: str, backend: Backend | None = None) -> dict:
    s1 = (backend or Live()).s1()
    s = SCREEN.ask({"tool": tool, "result": result_text[:3000]}, client=s1)  # 1 request
    verdict = case[
        (s.malicious >= 0.70) | (s.exfiltrating >= 0.70) : "block",
        ...:"allow",
    ].ask({})
    return {
        "verdict": verdict,
        "severity": float(s.severity),
        **({"why": "bad result"} if verdict == "block" else {}),
    }
