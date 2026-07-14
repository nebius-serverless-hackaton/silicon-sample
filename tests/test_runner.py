import asyncio
import uuid

import httpx
import pytest
from openai import APITimeoutError, RateLimitError

from silicon.core.llm import ask
from silicon.run.registry import existing_pairs
from silicon.run.runner import (
    CORRECTIVE,
    execute,
    flush_results,
    pending_tasks,
    run_task,
)


def fake_ask_fn(replies):
    """Pops canned replies in order; lets tests script the model's behavior."""
    queue = list(replies)

    async def _ask(messages):
        return queue.pop(0), 10, 20

    return _ask


class FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome

        class Msg:
            content = outcome

        class Choice:
            message = Msg()

        class Usage:
            prompt_tokens = 5
            completion_tokens = 7

        class Resp:
            choices = [Choice()]
            usage = Usage()

        return Resp()


class FakeClient:
    def __init__(self, outcomes):
        self.chat = type(
            "Chat", (), {"completions": FakeCompletions(outcomes)}
        )()


def timeout_error():
    return APITimeoutError(request=httpx.Request("POST", "http://test"))


def rate_limit_error():
    req = httpx.Request("POST", "http://test")
    resp = httpx.Response(429, headers={"retry-after": "0"}, request=req)
    return RateLimitError("rate limited", response=resp, body=None)


@pytest.mark.parametrize(
    "outcomes,expected_calls",
    [
        (['{"answer": "Favor"}'], 1),
        ([timeout_error(), '{"answer": "Favor"}'], 2),
        ([rate_limit_error(), timeout_error(), '{"answer": "Favor"}'], 3),
        ([timeout_error()] * 3, 3),
    ],
    ids=["first-try", "timeout-then-ok", "429-timeout-then-ok", "gives-up-after-attempts"],
)
def test_ask_transport_retries(outcomes, expected_calls):
    client = FakeClient(outcomes)
    gives_up = all(isinstance(o, Exception) for o in outcomes)
    call = ask(
        client,
        "m",
        [{"role": "user", "content": "x"}],
        temperature=1.0,
        max_tokens=10,
        attempts=len(outcomes),
        base_delay=0.001,
    )
    if gives_up:
        with pytest.raises(APITimeoutError):
            asyncio.run(call)
    else:
        text, ptok, ctok = asyncio.run(call)
        assert text == '{"answer": "Favor"}'
        assert (ptok, ctok) == (5, 7)
    assert client.chat.completions.calls == expected_calls


@pytest.mark.parametrize(
    "replies,expected_code,expected_retries,expect_error",
    [
        (['{"answer": "1"}'], 1, 0, False),
        (["garbage", '{"answer": "2"}'], 2, 1, False),
        (["garbage", "more garbage", "still bad"], None, 2, True),
    ],
    ids=["clean", "reask-recovers", "permanent-failure"],
)
def test_run_task_contract_loop(
    question_factory, replies, expected_code, expected_retries, expect_error
):
    q = question_factory()
    result = asyncio.run(run_task(fake_ask_fn(replies), 0, "sys", "user", q))
    assert result.code == expected_code
    assert result.retries == expected_retries
    assert (result.error is not None) == expect_error
    assert result.prompt_tokens == 10 * len(replies)


def test_run_task_reask_includes_corrective(question_factory):
    seen = []

    async def spy_ask(messages):
        seen.append([m["content"] for m in messages])
        return ("bad" if len(seen) == 1 else '{"answer": "1"}'), 1, 1

    asyncio.run(run_task(spy_ask, 0, "sys", "user", question_factory()))
    assert len(seen) == 2
    assert seen[1][-1] == CORRECTIVE
    assert seen[1][-2] == "bad"


def test_pending_tasks_skips_done():
    tasks = pending_tasks([0, 1], ["a", "b"], done={(0, "a"), (1, "b")})
    assert tasks == [(0, "b"), (1, "a")]


def test_execute_writes_all_results(mem_con, question_factory):
    q = question_factory()
    run_id = uuid.uuid4()
    tasks = [(a, q.qid) for a in range(7)]
    ask_fn = fake_ask_fn(['{"answer": "1"}'] * 7)
    asyncio.run(
        execute(
            mem_con,
            run_id,
            ask_fn,
            tasks,
            systems={a: "sys" for a in range(7)},
            question_msgs={q.qid: "user"},
            questions={q.qid: q},
            concurrency=3,
            batch_size=2,  # forces multiple flushes + a partial final batch
        )
    )
    n, codes = mem_con.execute(
        "SELECT count(*), count(DISTINCT code) FROM answers_synth WHERE run_id = ?",
        [run_id],
    ).fetchone()
    assert n == 7
    assert codes == 1
    assert existing_pairs(mem_con, run_id) == set(tasks)


def test_delete_run_removes_all_traces(mem_con):
    from silicon.run.registry import create_run, delete_run

    run_id = create_run(
        mem_con, panel_id=uuid.uuid4(), template_id="v1", model="m",
        temperature=1.0, question_set="all", n_agents=1, n_questions=1, config={},
    )
    mem_con.execute(
        "INSERT INTO answers_synth VALUES (?, 0, 'q', 1, 'raw', NULL, 0, 1, 1, 1, now())", [run_id]
    )
    mem_con.execute(
        "INSERT INTO scores VALUES (?, 'q', 'all', 'all', 1.0, 0.1, 1, 1, false)", [run_id]
    )
    delete_run(mem_con, run_id)
    for table in ("runs", "answers_synth", "scores"):
        assert mem_con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_flush_results_preserves_failure_rows(mem_con, question_factory):
    from silicon.run.runner import TaskResult

    run_id = uuid.uuid4()
    flush_results(
        mem_con,
        run_id,
        [
            TaskResult(
                0,
                "gss:cappun",
                None,
                "raw",
                "no JSON object in reply",
                2,
                30,
                60,
                500,
            )
        ],
    )
    code, error, retries = mem_con.execute(
        "SELECT code, error, retries FROM answers_synth WHERE run_id = ?",
        [run_id],
    ).fetchone()
    assert code is None
    assert "JSON" in error
    assert retries == 2
