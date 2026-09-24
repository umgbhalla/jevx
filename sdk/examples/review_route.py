"""Route a ticket and check a drafted reply in one Jev request.

Run live with ``uv run --env-file .env python examples/review_route.py``.
"""

from pydantic import BaseModel
from pydantic import computed_field

import jevx as j


class Review(BaseModel):
    resolved: j.NoulAnswer = (
        j.ask("Does the draft resolve the user's request?")
        | j.yes({"what": "Addresses the requested outcome with usable detail"})
        | j.no({"what": "Misses a necessary part or gives an unusable answer"})
    )
    route: j.ChoiceAnswer = (
        j.ask({
            "question": "Which team owns the ticket's primary issue?",
            "focus": "Classify the problem, not the customer's tone.",
        })
        | j.option("billing", {
            "what": "Charges, invoices, payments, refunds",
            "not_for": "A broken product feature",
        })
        | j.option("support", {
            "what": "Product use, bugs, troubleshooting",
            "not_for": "A charge dispute without a product defect",
        })
        | j.option("human", {"what": "An exception or decision requiring a person"})
    )

    @computed_field
    @property
    def send(self) -> bool:
        return self.resolved.noul >= 0.8 and self.route.choice != "human"


STATE = {
    "ticket": {
        "message": "Export to PDF spins forever. Chrome 128 on macOS. Third report this month."
    },
    "account": {"recent_charges": []},
    "draft": "I see the repeated PDF export failure. I have sent your steps to support.",
}


if __name__ == "__main__":
    with j.Client() as client:
        review = client.create(response_model=Review, state=STATE)
    print(review.model_dump())
