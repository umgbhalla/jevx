"""One shared ticket, three parallel Scores, and a local priority formula.

Run live with ``uv run --env-file .env python examples/pydantic_triage.py``.
"""

from pydantic import BaseModel
from pydantic import computed_field

import jevx as j


class Triage(BaseModel):
    severity: j.ScoreAnswer = (
        j.ask("How severe is the reported issue?")
        | j.level("Cosmetic; no impact to functionality")
        | j.level("Broken or degraded feature, but workaround exists")
        | j.level("Blocking issue; no workaround exists")
    )
    frustration: j.ScoreAnswer = (
        j.ask("How frustrated is the customer?")
        | j.level("Calm, just stating facts")
        | j.level("Frustrated but civil")
        | j.level("Very angry, strong language or threatening to leave")
    )
    report_quality: j.ScoreAnswer = (
        j.ask("How much does the report give an engineer to work with?")
        | j.level("No detail; just says something is broken")
        | j.level("Names the feature but no steps or environment")
        | j.level("Steps to reproduce or environment, but not both")
        | j.level("Steps to reproduce and environment")
    )

    @computed_field
    @property
    def priority(self) -> float:
        return (
            0.6 * self.severity.score / 2
            + 0.3 * self.frustration.score / 2
            + 0.1 * self.report_quality.score / 3
        )


TICKET = (
    "Export to PDF fails with a spinner that never finishes. Some of our team say CSV export "
    "still works for them, others say it fails too. This is the third time I'm writing in and "
    "honestly I'm done. Steps: open any report, click Export, choose PDF. Chrome 128 on macOS."
)


if __name__ == "__main__":
    with j.Client() as client:
        triage = client.create(response_model=Triage, state=TICKET)
    print(triage.model_dump())
