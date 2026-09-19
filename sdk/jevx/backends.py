"""Backend bundles: one object carries S1 + S2.

    bk = Live()                    # real API + real Codex (lazy)
    bk = Sim(s1_script={...}, s2_texts=[...])   # fully offline

    def handle(ticket, backend=None):
        bk = backend or Live()
        t = Triage(client=bk.s1())(ticket)
        draft = bk.s2().ask(...)

Class-composition form via __mro_entries__:

    class Flow(Uses(Sim(...))):
        def run(self, ticket):
            t = Triage(client=self.make_s1())(ticket)
"""

from __future__ import annotations

from typing import Any

from .fx import LiveDriver, ScriptDriver


class Backend:
    def s1(self):
        raise NotImplementedError

    def s2(self):
        raise NotImplementedError


class Live(Backend):
    """Real backends, constructed lazily (no key needed until first call)."""

    def __init__(self, model: str | None = None, s2_model: str = "gpt-5.6",
                 sandbox: str = "workspace-write"):
        self.model = model
        self.s2_model = s2_model
        self.sandbox = sandbox

    def s1(self):
        from .client import Client
        return Client(model=self.model)

    def s2(self):
        from .s2 import LazyS2
        return LazyS2(model=self.s2_model, sandbox=self.sandbox)


class Sim(Backend):
    """Offline backend: scripted S1 answers + scripted S2 texts."""

    def __init__(self, s1_script: dict[str, list[dict]] | None = None,
                 s2_texts: list[str] | None = None):
        self.s1_script = s1_script or {}
        self.s2_texts = s2_texts or []

    def s1(self):
        from .client import Response

        driver = ScriptDriver(self.s1_script)

        class _C:
            def system_one(_self, state, questions, model=None):
                return Response(driver.answer(state, questions), "sim", {})

        return _C()

    def s2(self):
        from .s2 import FakeSystem2
        return FakeSystem2(list(self.s2_texts))


class Uses:
    """Uses(bundle) in bases injects make_s1/make_s2 bound to that bundle."""

    def __init__(self, backend: Backend):
        self.backend = backend

    def __mro_entries__(self, bases: tuple) -> tuple:
        backend = self.backend

        class _M:
            def make_s1(self):
                return backend.s1()

            def make_s2(self):
                return backend.s2()

        _M.__name__ = f"Uses[{type(backend).__name__}]"
        return (_M,)
