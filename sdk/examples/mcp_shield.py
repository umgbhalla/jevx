"""MCP firewall: screen tool calls, results, and descriptions semantically.

Every tool invocation passes a 3-Noul battery (malicious? exfiltrating?
destructive?) plus a severity Score. Blocked calls never execute; blocked
results never reach the model. Allowlisted read-only tools skip free.
"""

from __future__ import annotations

import jevx as j
from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure

x = j.x

READ_ONLY = {"read", "glob", "grep", "list", "describe", "search"}


SCREEN = j.vector(
    malicious=j.noul("Does this tool call or result serve an attacker's goal?"),
    exfiltrating=j.noul("Does this move secrets or private data outward?"),
    destructive=j.noul("Does this destroy data or change external state?"),
    severity=j.score("Worst-case severity?", ("harmless", "suspicious", "dangerous")),
)

POLICY = j.case[
    (x.screen.malicious >= 0.70) | (x.screen.exfiltrating >= 0.70):
        j.stop("block", verdict="block", why="malicious/exfiltrating", severity=x.screen.severity),
    (x.screen.destructive >= 0.70) & (x.screen.severity >= 1.5):
        j.stop("block", verdict="block", why="destructive", severity=x.screen.severity),
    (x.screen.destructive >= 0.70) | (x.screen.severity >= 1.0):
        j.stop("review", verdict="review", severity=x.screen.severity),
    ...: j.stop("allow", verdict="allow", severity=x.screen.severity),
]

CALL = (
    j.input(tool=x, args=x)
    | j.keep(screen=SCREEN.on({"tool": x.tool, "args": x.args}))
    | POLICY
)

RESULT = (
    j.input(tool=x, result=x)
    | j.keep(screen=SCREEN.on({"tool": x.tool, "result": x.result[:3000]}))
    | j.case[
        (x.screen.malicious >= 0.70) | (x.screen.exfiltrating >= 0.70):
            j.stop("block", verdict="block", severity=x.screen.severity, why="bad result"),
        ...: j.stop("allow", verdict="allow", severity=x.screen.severity),
    ]
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
    return CALL.run(tool=tool, args=args, backend=backend or Live())


@ensure(
    lambda *a, result=None, **k: (
        result is not None and result["verdict"] in ("allow", "block", "review")
    ),
    msg="known shield verdict",
)
def screen_result(tool: str, result_text: str, backend: Backend | None = None) -> dict:
    return RESULT.run(tool=tool, result=result_text, backend=backend or Live())
