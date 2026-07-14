import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter

import duckdb

from silicon.data.conf import Question
from silicon.panel.prompts import ParseError, parse_answer

CORRECTIVE = (
    "Your previous reply was not a valid answer. Respond with only a JSON object "
    '{"answer": "<exact text of exactly one of the offered options>"} and nothing else.'
)


@dataclass
class TaskResult:
    agent_id: int
    qid: str
    code: int | None
    raw: str
    error: str | None
    retries: int
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


def pending_tasks(
    agent_ids: list[int], qids: list[str], done: set[tuple[int, str]]
) -> list[tuple[int, str]]:
    return [(a, q) for a in agent_ids for q in qids if (a, q) not in done]


async def run_task(
    ask_fn,
    agent_id: int,
    system: str,
    user: str,
    question: Question,
    max_reasks: int = 2,
) -> TaskResult:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    ptok = ctok = 0
    text, error = "", None
    t0 = perf_counter()
    for attempt in range(max_reasks + 1):
        text, p, c = await ask_fn(messages)
        ptok += p
        ctok += c
        try:
            code = parse_answer(text, question)
            return TaskResult(
                agent_id,
                question.qid,
                code,
                text,
                None,
                attempt,
                ptok,
                ctok,
                int((perf_counter() - t0) * 1000),
            )
        except ParseError as e:
            error = str(e)
            messages = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": CORRECTIVE},
            ]
    return TaskResult(
        agent_id,
        question.qid,
        None,
        text,
        error,
        max_reasks,
        ptok,
        ctok,
        int((perf_counter() - t0) * 1000),
    )


def flush_results(
    con: duckdb.DuckDBPyConnection, run_id: uuid.UUID, buf: list[TaskResult]
) -> None:
    now = datetime.now(timezone.utc)
    con.executemany(
        "INSERT INTO answers_synth VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            [
                run_id,
                r.agent_id,
                r.qid,
                r.code,
                r.raw,
                r.error,
                r.retries,
                r.prompt_tokens,
                r.completion_tokens,
                r.latency_ms,
                now,
            ]
            for r in buf
        ],
    )


async def execute(
    con: duckdb.DuckDBPyConnection,
    run_id: uuid.UUID,
    ask_fn,
    tasks: list[tuple[int, str]],
    systems: dict[int, str],
    question_msgs: dict[str, str],
    questions: dict[str, Question],
    concurrency: int = 16,
    max_reasks: int = 2,
    batch_size: int = 25,
    on_result=None,
) -> None:
    queue: asyncio.Queue = asyncio.Queue()
    sem = asyncio.Semaphore(concurrency)

    async def writer():
        buf = []
        while True:
            item = await queue.get()
            if item is None:
                break
            buf.append(item)
            if len(buf) >= batch_size:
                flush_results(con, run_id, buf)
                buf = []
        if buf:
            flush_results(con, run_id, buf)

    async def one(agent_id: int, qid: str):
        async with sem:
            result = await run_task(
                ask_fn,
                agent_id,
                systems[agent_id],
                question_msgs[qid],
                questions[qid],
                max_reasks,
            )
        await queue.put(result)
        if on_result:
            on_result(result)

    writer_task = asyncio.create_task(writer())
    try:
        await asyncio.gather(*(one(a, q) for a, q in tasks))
    finally:
        # always let the writer drain what workers managed to produce
        await queue.put(None)
        await writer_task
