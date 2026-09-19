"""HTTP request router: NL route descriptions matched per request (hono-style).

Routes register {name: description + handler}. One Choice per request picks
the handler; confidence below bar → 404-style fallback. Pure function core;
thin stdlib http.server wiring included but never required.
"""

from __future__ import annotations

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.py import case


@ensure(
    lambda *a, result=None, **k: result is not None and ("handler" in result or "status" in result),
    msg="route resolves or 404s",
)
def route_request(
    method: str,
    path: str,
    body: str,
    routes: dict,
    backend: Backend | None = None,
    conf_at: float = 0.6,
) -> dict:
    from jevx.py import pick

    s1 = (backend or Live()).s1()
    c = pick(
        "which route handles this request?",
        {"method": method, "path": path, "body": body[:2000]},
        {n: r["description"] for n, r in routes.items()},
        client=s1,
    )
    return case[
        c.confidence < conf_at : {
            "status": 404,
            "route": None,
            "confidence": c.confidence,
        },
        ... : {
            "status": 200,
            "route": c.choice,
            "confidence": c.confidence,
            "handler": routes[c.choice]["handler"],
        },
    ].ask({})


def serve(
    routes: dict, host: str = "127.0.0.1", port: int = 8471, backend: Backend | None = None
) -> None:
    """Tiny stdlib server. S1 per request; production would add caching."""
    from http.server import BaseHTTPRequestHandler
    from http.server import HTTPServer

    class H(BaseHTTPRequestHandler):
        def _run(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode() if length else ""
            r = route_request(self.command, self.path, body, routes, backend)
            handler = r.get("handler")
            out = handler(self.path, body) if handler else "no route"
            coded = out.encode()
            self.send_response(r["status"])
            self.send_header("Content-Length", str(len(coded)))
            self.end_headers()
            self.wfile.write(coded)

        do_GET = do_POST = _run

        def log_message(self, format: str, *args: object) -> None:
            pass

    HTTPServer((host, port), H).serve_forever()
