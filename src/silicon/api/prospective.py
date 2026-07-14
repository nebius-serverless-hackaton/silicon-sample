import json
import re
import uuid
from datetime import datetime, timezone

import duckdb

from silicon.data.conf import Question, QuestionOption

DDL = """
CREATE TABLE IF NOT EXISTS prospective (
    qid VARCHAR PRIMARY KEY,
    text VARCHAR,
    options JSON,
    created_at TIMESTAMP
);
"""


def ensure_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(DDL)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:32] or uuid.uuid4().hex[:8]


def add_question(
    con: duckdb.DuckDBPyConnection,
    text: str,
    options: list[str],
    slug: str | None = None,
) -> Question:
    ensure_table(con)
    qid = f"new:{_slugify(slug or text)}"
    if con.execute("SELECT count(*) FROM prospective WHERE qid = ?", [qid]).fetchone()[
        0
    ]:
        raise ValueError(f"question {qid!r} already exists - pass a distinct slug")
    opts = [{"code": i + 1, "text": t} for i, t in enumerate(options)]
    con.execute(
        "INSERT INTO prospective VALUES (?, ?, ?, ?)",
        [qid, text, json.dumps(opts), datetime.now(timezone.utc)],
    )
    return _to_question(qid, text, opts)


def _to_question(qid: str, text: str, opts: list[dict]) -> Question:
    return Question(
        qid=qid,
        var=qid,
        qtype="single_choice",
        text=text,
        options=[QuestionOption(**o) for o in opts],
    )


def list_questions(con: duckdb.DuckDBPyConnection) -> list[Question]:
    ensure_table(con)
    rows = con.execute(
        "SELECT qid, text, options FROM prospective ORDER BY created_at"
    ).fetchall()
    return [_to_question(qid, text, json.loads(opts)) for qid, text, opts in rows]


def get_questions(
    con: duckdb.DuckDBPyConnection, qids: list[str]
) -> dict[str, Question]:
    return {q.qid: q for q in list_questions(con) if q.qid in set(qids)}
