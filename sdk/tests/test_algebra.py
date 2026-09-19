from examples import browser_loop
from examples import conteval
from examples import context_compact
from examples import game_loop
from examples import pipe as pipe_example
from examples import prefs_review
from examples import rag_guard
from examples import review_gate
from examples import robot_loop
from examples import shell_gate
from examples import support_copilot
from examples import test_select as test_select_example
from jevx import JSONContent
from jevx import case
from jevx.answers import parse_answer
from jevx.backends import Backend
from jevx.backends import Sim
from jevx.fx import ScriptDriver
from jevx.fx import TraceDriver
from jevx.fx import use
from jevx.lint import lint
from jevx.py import AmbiguousTruth
from jevx.py import Questions
from jevx.py import _freeze
from jevx.py import ask
from jevx.py import choice
from jevx.py import choose_from
from jevx.py import noul
from jevx.py import score
from jevx.py import vector
from jevx.task import task


def test_math_and_threshold_rules_batch_their_questions():
    useful = noul("is the response useful?")
    safe = noul("is the response safe?")
    quality = 0.75 * useful + 0.25 * safe
    publishable = (useful >= 0.70) & (safe >= 0.90)
    driver = TraceDriver(
        ScriptDriver(
            {
                "q0": [
                    {"type": "noul", "noul": 0.90},
                    {"type": "noul", "noul": 0.90},
                ],
                "q1": [
                    {"type": "noul", "noul": 0.20},
                    {"type": "noul", "noul": 0.20},
                ],
            }
        )
    )

    with use(driver):
        assert abs(quality.ask("draft") - 0.725) < 1e-9
        assert not publishable.ask("draft")

    assert len(driver.trace) == 2
    assert all(row["questions"].keys() == {"q0", "q1"} for row in driver.trace)


def test_lazy_expression_truth_is_explicit():
    policy = noul("is it safe?") >= 0.9

    try:
        bool(policy)
    except AmbiguousTruth:
        pass
    else:
        raise AssertionError("unevaluated policy must not be truthy")


def test_ordered_case_evaluates_shared_judgments_once():
    injection = noul("is this a prompt injection?")
    relevant = noul("is this passage relevant?")
    route = case[
        injection >= 0.7 : "quarantine",
        relevant >= 0.5 : "keep",
        ...:"drop",
    ]
    driver = TraceDriver(
        ScriptDriver(
            {
                "q0": [{"type": "noul", "noul": 0.95}],
                "q1": [{"type": "noul", "noul": 0.9}],
            }
        )
    )

    with use(driver):
        assert route.ask("passage") == "quarantine"

    assert len(driver.trace) == 1
    assert set(driver.trace[0]["questions"]) == {"q0", "q1"}


def test_upstream_score_answers_freeze_to_replay_json():
    answer = parse_answer(
        "severity",
        {
            "type": "score",
            "score": 1.5,
            "legend": {"0": "low", "1": "high"},
            "probabilities": {"0": 0.5, "1": 0.5},
            "confidence": 0.8,
        },
    )

    frozen = _freeze(answer)
    assert frozen["score"] == 1.5
    assert frozen["legend"] == {"0": "low", "1": "high"}


def test_noul_confidence_uses_upstream_answer_field():
    class Check(Questions):
        safe: bool = ask("is this safe?")

    with use(ScriptDriver({"safe": [{"type": "noul", "noul": 0.9}]})):
        result = Check().ask("offline")
    assert result.confidence("safe") == 0.8


def test_named_vector_batches_upstream_question_types():
    checks = vector(
        safe=noul("is the reply safe?"),
        team=choice("which team owns it?", ("billing", "bug")),
        severity=score("how severe is it?", ("low", "high")),
    )
    driver = TraceDriver(
        ScriptDriver(
            {
                "q0": [{"type": "noul", "noul": 0.95}],
                "q1": [
                    {
                        "type": "choice",
                        "choice": "billing",
                        "probabilities": {"billing": 0.9, "bug": 0.1},
                        "confidence": 0.9,
                    }
                ],
                "q2": [
                    {
                        "type": "score",
                        "score": 0.8,
                        "legend": {"0": "low", "1": "high"},
                        "probabilities": {"0": 0.2, "1": 0.8},
                        "confidence": 0.8,
                    }
                ],
            }
        )
    )

    with use(driver):
        result = checks.ask("ticket")

    assert float(result.safe) == 0.95
    assert result.team.choice == "billing"
    assert result.severity == 0.8
    assert result.severity.probabilities[1] == 0.8
    assert result.confidence("severity") == 0.8
    assert len(driver.trace) == 1
    assert set(driver.trace[0]["questions"]) == {"q0", "q1", "q2"}


def test_structured_entries_reach_typesafe_without_stringification():
    instructions: JSONContent = {
        "question": "Does extracted_value match source_text?",
        "field": "invoice_number",
    }
    entries = vector(
        supported=noul(
            instructions,
            true={"what": "Exact identifier match", "examples": ["4471"]},
            false=["Any different identifier", "Missing identifier"],
        ),
        department=choice(
            {"question": "Which team owns the request?", "focus": ["primary intent"]},
            {
                "billing": {"what": "Charges and refunds", "not_for": "Delivery status"},
                "orders": {"what": "Tracking and returns", "examples": ["Where is it?"]},
            },
        ),
        severity=score(
            {"question": "How serious is the issue?", "note": "Judge user impact."},
            [
                {"summary": "low", "signals": ["cosmetic"]},
                {"summary": "high", "signals": ["data loss", "outage"]},
            ],
        ),
    )
    driver = TraceDriver(
        ScriptDriver(
            {
                "q0": [{"type": "noul", "noul": 0.9}],
                "q1": [
                    {
                        "type": "choice",
                        "choice": "billing",
                        "probabilities": {"billing": 0.9, "orders": 0.1},
                        "confidence": 0.8,
                    }
                ],
                "q2": [
                    {
                        "type": "score",
                        "score": 1,
                        "legend": {"0": "low", "1": "high"},
                        "probabilities": {"0": 0.1, "1": 0.9},
                        "confidence": 0.9,
                    }
                ],
            }
        )
    )

    with use(driver):
        result = entries.ask({"invoice_number": "4471", "source_text": "Invoice 4471"})

    assert result.department.choice == "billing"
    assert driver.trace[0]["questions"]["q0"]["instructions"]["field"] == "invoice_number"
    assert driver.trace[0]["questions"]["q0"]["criteria"]["true"]["examples"] == ["4471"]
    assert driver.trace[0]["questions"]["q1"]["criteria"]["orders"]["examples"] == ["Where is it?"]
    assert driver.trace[0]["questions"]["q2"]["criteria"][1]["signals"] == ["data loss", "outage"]


def test_questions_class_accepts_structured_instructions_and_criteria():
    from typing import Literal

    from jevx.py import Score

    class Review(Questions):
        accepted: bool = ask(
            {"question": "Does the patch meet the policy?", "inspect": ["diff", "tests"]},
            criteria={"true": {"what": "all rules pass"}, "false": ["any rule fails"]},
        )
        route: Literal["security", "product"] = ask(
            {"question": "Which team owns it?"},
            criteria={
                "security": {"what": "Trust, access, and secrets"},
                "product": {"what": "Behavior and usability"},
            },
        )
        severity: Score[Literal["low", "high"]] = ask(
            {"question": "How serious is it?"},
            criteria=[{"summary": "low"}, {"summary": "high"}],
        )

    driver = TraceDriver(
        ScriptDriver(
            {
                "accepted": [{"type": "noul", "noul": 0.9}],
                "route": [
                    {
                        "type": "choice",
                        "choice": "security",
                        "probabilities": {"security": 0.8, "product": 0.2},
                        "confidence": 0.8,
                    }
                ],
                "severity": [
                    {
                        "type": "score",
                        "score": 1,
                        "legend": {"0": "low", "1": "high"},
                        "probabilities": {"0": 0.1, "1": 0.9},
                        "confidence": 0.9,
                    }
                ],
            }
        )
    )

    with use(driver):
        result = Review().ask("patch")

    assert result.accepted
    assert result.route == "security"
    assert driver.trace[0]["questions"]["route"]["criteria"]["security"]["what"].startswith("Trust")


def test_question_lint_accepts_structured_fields_and_finds_duplicate_rubrics():
    valid = {
        "n": {
            "type": "noul",
            "instructions": {"question": "Is this supported?", "inspect": ["claim", "sources"]},
            "criteria": {
                "true": {"what": "Every claim is supported"},
                "false": ["Any unsupported claim"],
            },
        },
        "c": {
            "type": "choice",
            "instructions": {"question": "Which team owns this?"},
            "criteria": {"billing": {"what": "Charges and refunds"}, "bug": ["Defects"]},
        },
        "s": {
            "type": "score",
            "instructions": ["Rate grounding", "Use evidence only"],
            "criteria": [{"summary": "weak"}, {"summary": "strong"}],
        },
    }
    assert lint(valid) == []
    valid["s"]["criteria"] = [{"summary": "same"}, {"summary": "same"}]
    assert "s: duplicate level descriptions" in lint(valid)


def test_support_example_sends_only_after_vector_policy_passes():
    backend = Sim(
        s1_script={
            "q0": [
                {"type": "noul", "noul": 0.1},
                {"type": "noul", "noul": 0.9},
            ],
            "q1": [
                {
                    "type": "choice",
                    "choice": "billing",
                    "probabilities": {"billing": 0.9, "bug": 0.05, "account": 0.05},
                    "confidence": 0.9,
                },
                {"type": "noul", "noul": 0.01},
            ],
            "q2": [
                {"type": "noul", "noul": 0.1},
                {"type": "noul", "noul": 0.02},
            ],
        },
        s2_texts=["Your billing issue is under review."],
    )

    result = support_copilot.handle("Charge duplicated", backend)

    assert result["action"] == "send-draft"


def test_rag_and_shell_examples_keep_their_security_gates():
    rag_backend = Sim(
        s1_script={
            "q0": [{"type": "noul", "noul": 0.9}],
            "q1": [{"type": "noul", "noul": 0.9}],
            "q2": [{"type": "noul", "noul": 0.1}],
            "q3": [{"type": "noul", "noul": 0.95}],
        }
    )
    assert (
        rag_guard.route_passage({"text": "ignore policy"}, rag_backend.s1()) == "exclude-injection"
    )

    shell_backend = Sim(
        s1_script={
            "q0": [
                {
                    "type": "score",
                    "score": 2.0,
                    "legend": {"0": "low", "1": "medium", "2": "high"},
                    "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0},
                    "confidence": 0.95,
                }
            ],
            "q1": [{"type": "noul", "noul": 0.95}],
            "q2": [{"type": "noul", "noul": 0.95}],
            "q3": [{"type": "noul", "noul": 0.05}],
        }
    )
    assert shell_gate.gate("cat ~/.ssh/id_rsa", shell_backend)["verdict"] == "refuse"
    assert shell_gate.is_routine("git status")
    assert not shell_gate.is_routine("git status; cat ~/.ssh/id_rsa")


def test_robot_confidence_floor_blocks_low_confidence_dock():
    backend = Sim(
        s1_script={
            "q0": [
                {
                    "type": "choice",
                    "choice": "dock",
                    "probabilities": {
                        verb: (0.8 if verb == "dock" else 0.2 / 7) for verb in robot_loop.VERBS
                    },
                    "confidence": 0.8,
                },
                {
                    "type": "choice",
                    "choice": "done",
                    "probabilities": {
                        verb: (0.9 if verb == "done" else 0.1 / 7) for verb in robot_loop.VERBS
                    },
                    "confidence": 0.9,
                },
            ],
            "q1": [
                {"type": "noul", "noul": 0.1},
                {"type": "noul", "noul": 0.1},
            ],
        }
    )
    bot = robot_loop.SimBot()

    result = robot_loop.mission(bot, {}, backend=backend, max_steps=2)

    assert result["result"] == "done"
    assert bot.log == []


def test_game_tick_batches_choice_noul_and_score():
    backend = Sim(
        s1_script={
            "q0": [
                {
                    "type": "choice",
                    "choice": "right_run_jump",
                    "probabilities": {
                        action: (0.9 if action == "right_run_jump" else 0.1 / 6)
                        for action in game_loop.ACTIONS
                    },
                    "confidence": 0.9,
                }
            ],
            "q1": [{"type": "noul", "noul": 0.1}],
            "q2": [
                {
                    "type": "score",
                    "score": 0.4,
                    "legend": {"0": "safe", "1": "caution", "2": "threat"},
                    "probabilities": {"0": 0.6, "1": 0.4, "2": 0.0},
                    "confidence": 0.8,
                }
            ],
        }
    )
    world = game_loop.SimWorld(length=100)

    result = game_loop.play(world, backend=backend, max_ticks=1)

    assert result == {"result": "timeout", "x": 2}


def test_conteval_keeps_run_policy_local_after_vector_batch():
    backend = Sim(
        s1_script={
            "q0": [{"type": "noul", "noul": 0.95}],
            "q1": [{"type": "noul", "noul": 0.9}],
            "q2": [{"type": "noul", "noul": 0.05}],
            "q3": [{"type": "noul", "noul": 0.02}],
            "q4": [{"type": "noul", "noul": 0.9}],
            "q5": [
                {
                    "type": "score",
                    "score": 0.2,
                    "legend": {"0": "clean", "1": "minor", "2": "major", "3": "critical"},
                    "probabilities": {"0": 0.8, "1": 0.2, "2": 0.0, "3": 0.0},
                    "confidence": 0.9,
                }
            ],
            "q6": [
                {
                    "type": "choice",
                    "choice": "ship",
                    "probabilities": {"ship": 0.95, "fixup": 0.03, "rollback": 0.02},
                    "confidence": 0.95,
                }
            ],
            "q7": [
                {
                    "type": "choice",
                    "choice": "none",
                    "probabilities": {
                        "logic": 0.01,
                        "test_gap": 0.01,
                        "security": 0.01,
                        "perf": 0.01,
                        "none": 0.96,
                    },
                    "confidence": 0.96,
                }
            ],
        }
    )

    result = conteval.judge_run({"diff": "small, covered change"}, backend)

    assert result["route"] == "auto-ship"
    assert result["secure_ok"] is True


def test_preference_review_uses_public_dynamic_vector_and_keeps_hunk_context():
    class OfflineBackend(Backend):
        def s1(self):
            return None

    driver = TraceDriver(
        ScriptDriver(
            {
                "q0": [{"type": "noul", "noul": 0.95}],
                "q1": [{"type": "noul", "noul": 0.05}],
            }
        )
    )
    prefs = {"secrets": "Never expose credentials in logs."}
    hunks = [
        {"file": "app/log.py", "hunk": "+logger.info(token)"},
        {"file": "app/cli.py", "hunk": "+print('ready')"},
    ]

    with use(driver):
        result = prefs_review.review_diff(prefs, hunks, backend=OfflineBackend())

    assert result["action"] == "block"
    assert result["violations"][0]["file"] == "app/log.py"
    assert len(driver.trace) == 1
    assert set(driver.trace[0]["questions"]) == {"q0", "q1"}
    first = driver.trace[0]["questions"]["q0"]["instructions"]
    assert first["preference"]["rule"] == prefs["secrets"]
    assert first["change"]["hunk"] == hunks[0]["hunk"]


def test_browser_fanout_uses_public_vector_in_one_request():
    operations = tuple(browser_loop.OP_DESCRIPTIONS)
    targets = {"e_submit_login": 1.0}
    script = {
        "q0": [
            {
                "type": "choice",
                "choice": "CLICK",
                "probabilities": {op: (0.8 if op == "CLICK" else 0.2 / 8) for op in operations},
                "confidence": 0.8,
            }
        ],
        **{
            f"q{index}": [
                {
                    "type": "choice",
                    "choice": "e_submit_login",
                    "probabilities": targets,
                    "confidence": 1.0,
                }
            ]
            for index in range(1, len(browser_loop.HEADS) + 1)
        },
    }
    driver = TraceDriver(ScriptDriver(script))
    snap = {
        "url": "/login",
        "title": "login",
        "text": "login form",
        "elements": [{"index": "e_submit_login", "label": "Log in"}],
    }

    with use(driver):
        selected = browser_loop.choose("log in", snap, [], None)

    assert selected == ("CLICK", "e_submit_login", 0.8, targets)
    assert len(driver.trace) == 1
    assert set(driver.trace[0]["questions"]) == {"q0", "q1", "q2", "q3", "q4"}


def test_test_selector_batches_rows_and_runs_the_review_band():
    class OfflineBackend:
        def s1(self):
            return None

    driver = TraceDriver(
        ScriptDriver(
            {
                "r0": [{"type": "noul", "noul": 0.1}],
                "r1": [{"type": "noul", "noul": 0.5}],
            }
        )
    )
    tests = [
        {"id": "a", "path": "src/a.py", "framework": "pytest"},
        {"id": "b", "path": "src/b.py", "framework": "pytest"},
    ]

    with use(driver):
        selected = test_select_example.select("diff", tests, backend=OfflineBackend())

    assert [test["id"] for test in selected["skip"]] == ["a"]
    assert [test["id"] for test in selected["review"]] == ["b"]
    assert [test["id"] for test in selected["run"]] == ["b"]
    assert len(driver.trace) == 1
    questions = driver.trace[0]["questions"]
    assert questions["r0"]["instructions"]["record"] == tests[0]
    assert driver.trace[0]["state"]["context"]["diff"] == "diff"


def test_context_compaction_batches_exchanges_and_keeps_dropped_audit():
    class OfflineBackend:
        def s1(self):
            return None

    driver = TraceDriver(
        ScriptDriver(
            {
                "r0": [{"type": "noul", "noul": 0.9}],
                "r1": [{"type": "noul", "noul": 0.1}],
            }
        )
    )
    exchanges = [
        {"role": "user", "content": "Fix the billing bug."},
        {"role": "assistant", "content": "Unrelated old note."},
    ]

    with use(driver):
        compacted = context_compact.compact(exchanges, "fix billing", backend=OfflineBackend())

    assert compacted["kept"] == [exchanges[0]]
    assert compacted["dropped"][0]["index"] == 1
    assert compacted["dropped"][0]["prob"] == 0.1
    assert len(driver.trace) == 1


def test_task_history_records_value_vector_calls():
    backend = Sim(
        s1_script={
            "q0": [
                {"type": "noul", "noul": 0.9},
                {"type": "noul", "noul": 0.9},
            ],
            "q1": [
                {"type": "noul", "noul": 0.1},
                {"type": "noul", "noul": 0.9},
            ],
        }
    )
    checks = vector(supported=noul("is it supported?"), risky=noul("is it risky?"))

    with task("review", backend) as run:
        result = run.ask(checks, {"draft": "text"})
        approved = run.ask(
            (noul("are claims supported?") >= 0.8) & (noul("is it safe?") >= 0.7),
            {"draft": "text"},
        )

    assert result.supported == 0.9
    assert approved is True
    assert run.history[-2]["summary"] == "supported, risky"
    assert run.history[-2]["kind"] == "jev.vector"
    assert run.history[-1]["kind"] == "jev.rule"
    assert run.history[-1]["summary"] == "threshold rule"
    assert set(run.history[-2]["questions"]) == {"q0", "q1"}
    assert set(run.history[-1]["questions"]) == {"q0", "q1"}


def test_review_gate_runs_screen_as_one_named_vector():
    class OfflineBackend:
        def s1(self):
            return None

        def s2(self):
            return None

    driver = TraceDriver(
        ScriptDriver(
            {f"q{i}": [{"type": "noul", "noul": 0.1}] for i in range(5)}
        )
    )
    pr = {"files": [{"path": "src/app.py", "patch": "+x = 1", "hunks": ["+x = 1"]}]}

    with use(driver):
        result = review_gate.review(pr, backend=OfflineBackend())

    assert result == {"action": "approve", "findings": []}
    assert len(driver.trace) == 1
    assert set(driver.trace[0]["questions"]) == {"q0", "q1", "q2", "q3", "q4"}


def test_pipe_batches_lines_and_keeps_keep_threshold_in_code():
    class OfflineBackend(Backend):
        def s1(self):
            return None

    driver = TraceDriver(
        ScriptDriver(
            {
                "r0": [{"type": "noul", "noul": 0.8}],
                "r1": [{"type": "noul", "noul": 0.2}],
            }
        )
    )

    with use(driver):
        result = pipe_example.judge_lines(
            "is this actionable?", ["error: missing file", "progress: 10%"], OfflineBackend()
        )

    assert [row["verdict"] for row in result] == ["KEEP", "DROP"]
    assert len(driver.trace) == 1
    question = driver.trace[0]["questions"]["r0"]["instructions"]
    assert question["record"]["line"] == "error: missing file"


def test_choose_from_supports_described_vector_routes():
    routes = {
        "billing": vector(urgent=noul("Reply within the hour?") >= 0.5),
        "spam": lambda state: {"action": "drop"},
    }
    driver = TraceDriver(
        ScriptDriver(
            {
                "c": [{
                    "type": "choice",
                    "choice": "billing",
                    "probabilities": {"billing": 0.9, "spam": 0.1},
                    "confidence": 0.8,
                }],
                "q0": [{"type": "noul", "noul": 0.9}],
            }
        )
    )

    with use(driver):
        route, filled = choose_from(
            "ticket",
            routes,
            descriptions={"billing": {"what": "Charges and refunds"}},
        )

    assert route == "billing"
    assert filled.urgent is True
    assert len(driver.trace) == 2
    assert driver.trace[0]["questions"]["c"]["criteria"]["billing"] == {
        "what": "Charges and refunds"
    }
    assert set(driver.trace[1]["questions"]) == {"q0"}
