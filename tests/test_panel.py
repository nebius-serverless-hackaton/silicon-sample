import numpy as np
import pytest

from silicon.data.conf import load_questions
from silicon.panel.prompts import (
    ParseError,
    parse_answer,
    render_question,
    render_system,
)
from silicon.panel.sample import bootstrap_indices

QUESTIONS = {q.qid: q for q in load_questions()}
TEMPLATES = ["v1_neutral", "v2_persona_rich", "v3_minimal"]


def test_bootstrap_deterministic():
    w = [1.0, 2.0, 3.0]
    assert (bootstrap_indices(w, 50, seed=7) == bootstrap_indices(w, 50, seed=7)).all()
    assert (bootstrap_indices(w, 50, seed=7) != bootstrap_indices(w, 50, seed=8)).any()


def test_bootstrap_respects_weights():
    idx = bootstrap_indices([100.0, 1.0, 1.0], 1000, seed=1)
    assert np.mean(idx == 0) > 0.9
    assert len(idx) == 1000


@pytest.fixture(
    params=[
        {
            "income_bracket": "$50,000 – $89,999",
            "work": "working full time",
            "children": 2,
        },
        {"income_bracket": None, "work": None, "children": None},
    ],
    ids=["full-profile", "missing-optionals"],
)
def profile(request):
    base = {
        "agent_id": 0,
        "resp_id": "gss:2024:1",
        "year": 2024,
        "age": 33,
        "yob": 1991,
        "sex": "male",
        "race": "black",
        "region": "northeast",
        "education": "bachelor's degree",
        "marital": "never married",
        "religion": "Protestant",
        "attend": "attends religious services every week",
        "weight": 1.0,
        "dataset": "gss",
        "ballot": 2,
    }
    return base | request.param


@pytest.mark.parametrize("template", TEMPLATES)
def test_templates_render(template, profile):
    out = render_system(template, profile)
    assert "1991" in out
    assert "JSON" in out
    assert "None" not in out


def test_render_question_lists_options():
    out = render_question(QUESTIONS["gss:cappun"])
    assert "death penalty" in out
    assert "- Favor" in out and "- Oppose" in out


@pytest.mark.parametrize(
    "style,in_list,in_last_resort",
    [
        ("listed", True, False),
        ("last-resort", False, True),
        ("hidden", False, False),
    ],
    ids=["listed", "last-resort", "hidden"],
)
def test_render_question_volunteered_styles(style, in_list, in_last_resort):
    out = render_question(QUESTIONS["gss:trust"], volunteered_style=style)
    assert ("- Depends" in out) == in_list
    # quoted (not listed) means it rendered via the last-resort clause, whatever its wording
    assert ('"Depends"' in out) == in_last_resort
    assert "Most people can be trusted" in out  # real options always present


def test_render_question_rejects_unknown_style():
    with pytest.raises(ValueError):
        render_question(QUESTIONS["gss:trust"], volunteered_style="bogus")


def test_last_resort_no_volunteered_options_renders_plain():
    out = render_question(QUESTIONS["gss:cappun"], volunteered_style="last-resort")
    assert "cannot choose" not in out


@pytest.mark.parametrize(
    "run_style,qid,expected",
    [
        ("auto", "gss:helpful", "last-resort"),  # calibrated in YAML
        ("auto", "gss:courts", "listed"),  # no YAML override
        ("listed", "gss:helpful", "listed"),  # global override beats YAML
        ("hidden", "gss:courts", "hidden"),
    ],
    ids=["auto-calibrated", "auto-default", "override-wins", "override-hidden"],
)
def test_resolve_style(run_style, qid, expected):
    from silicon.run.orchestrate import resolve_style

    assert resolve_style(run_style, QUESTIONS[qid]) == expected


@pytest.mark.parametrize(
    "raw,qid,expected",
    [
        ('{"answer": "Favor"}', "gss:cappun", 1),
        ('{"answer": "  oppose. "}', "gss:cappun", 2),
        ('<think>hmm, tough one</think>{"answer": "Favor"}', "gss:cappun", 1),
        (
            'Sure! Here is my answer: {"answer": "Oppose"} hope that helps',
            "gss:cappun",
            2,
        ),
        ('{"answer": "4"}', "gss:eqwlth", 4),
        ('{"answer": 4}', "gss:eqwlth", 4),
        (
            '{"answer": "7 - Government should not concern itself with income differences"}',
            "gss:eqwlth",
            7,
        ),
        ('{"answer": "Strong Democrat"}', "gss:partyid", 0),
    ],
    ids=[
        "exact",
        "case-space-period",
        "think-block",
        "chatter",
        "bare-number",
        "json-int",
        "full-scale-text",
        "code-zero",
    ],
)
def test_parse_answer_accepts(raw, qid, expected):
    assert parse_answer(raw, QUESTIONS[qid]) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "I would say Favor",
        '{"answer": "Strongly favor"}',
        '{"answer": "8"}',
        '{"choice": "Favor"}',
        '{"answer": ',
    ],
    ids=[
        "no-json",
        "not-an-option",
        "code-out-of-range",
        "wrong-key",
        "truncated",
    ],
)
def test_parse_answer_rejects(raw):
    with pytest.raises(ParseError):
        parse_answer(raw, QUESTIONS["gss:cappun"])
