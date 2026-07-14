import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import yaml

DDL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id UUID PRIMARY KEY,
    created_at TIMESTAMP,
    status VARCHAR,
    panel_id UUID,
    template_id VARCHAR,
    model VARCHAR,
    temperature DOUBLE,
    question_set VARCHAR,
    n_agents INTEGER,
    n_questions INTEGER,
    n_answered INTEGER,
    n_failed INTEGER,
    prompt_tokens BIGINT,
    completion_tokens BIGINT,
    cost_usd DOUBLE,
    config JSON,
    mae DOUBLE,
    js_distance DOUBLE
);
CREATE TABLE IF NOT EXISTS answers_synth (
    run_id UUID,
    agent_id INTEGER,
    qid VARCHAR,
    code SMALLINT,
    raw_response VARCHAR,
    error VARCHAR,
    retries TINYINT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    latency_ms INTEGER,
    created_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS scores (
    run_id UUID,
    qid VARCHAR,
    subgroup_dim VARCHAR,
    subgroup_value VARCHAR,
    mae DOUBLE,
    js_distance DOUBLE,
    n_synth INTEGER,
    n_target INTEGER,
    low_n BOOLEAN
);
"""


def ensure_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(DDL)


def create_run(
    con: duckdb.DuckDBPyConnection,
    panel_id: uuid.UUID,
    template_id: str,
    model: str,
    temperature: float,
    question_set: str,
    n_agents: int,
    n_questions: int,
    config: dict,
) -> uuid.UUID:
    ensure_tables(con)
    run_id = uuid.uuid4()
    con.execute(
        """INSERT INTO runs (run_id, created_at, status, panel_id, template_id, model,
           temperature, question_set, n_agents, n_questions, n_answered, n_failed,
           prompt_tokens, completion_tokens, cost_usd, config)
           VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, NULL, ?)""",
        [
            run_id,
            datetime.now(timezone.utc),
            panel_id,
            template_id,
            model,
            temperature,
            question_set,
            n_agents,
            n_questions,
            json.dumps(config),
        ],
    )
    return run_id


def get_run(con: duckdb.DuckDBPyConnection, run_id: uuid.UUID) -> dict:
    df = con.execute("SELECT * FROM runs WHERE run_id = ?", [run_id]).df()
    if df.empty:
        raise RuntimeError(f"run {run_id} not found")
    run = df.iloc[0].to_dict()
    run["config"] = json.loads(run["config"])
    return run


def set_status(
    con: duckdb.DuckDBPyConnection, run_id: uuid.UUID, status: str
) -> None:
    con.execute("UPDATE runs SET status = ? WHERE run_id = ?", [status, run_id])


def load_prices(path: str = "config/models.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def finalize_run(
    con: duckdb.DuckDBPyConnection, run_id: uuid.UUID, status: str
) -> dict:
    answered, failed, ptok, ctok = con.execute(
        """SELECT count(code), count(*) - count(code),
                  coalesce(sum(prompt_tokens), 0), coalesce(sum(completion_tokens), 0)
           FROM answers_synth WHERE run_id = ?""",
        [run_id],
    ).fetchone()
    model = con.execute(
        "SELECT model FROM runs WHERE run_id = ?", [run_id]
    ).fetchone()[0]
    price = load_prices().get(model)
    cost = (
        (ptok * price["input"] + ctok * price["output"]) / 1_000_000
        if price
        else None
    )
    con.execute(
        """UPDATE runs SET status = ?, n_answered = ?, n_failed = ?,
           prompt_tokens = ?, completion_tokens = ?, cost_usd = ? WHERE run_id = ?""",
        [status, answered, failed, ptok, ctok, cost, run_id],
    )
    return {
        "run_id": str(run_id),
        "status": status,
        "answered": answered,
        "failed": failed,
        "prompt_tokens": ptok,
        "completion_tokens": ctok,
        "cost_usd": cost,
    }


def existing_pairs(
    con: duckdb.DuckDBPyConnection, run_id: uuid.UUID
) -> set[tuple[int, str]]:
    ensure_tables(con)
    rows = con.execute(
        "SELECT agent_id, qid FROM answers_synth WHERE run_id = ?", [run_id]
    ).fetchall()
    return set(rows)


def delete_run(con: duckdb.DuckDBPyConnection, run_id: uuid.UUID) -> None:
    ensure_tables(con)
    con.execute("DELETE FROM scores WHERE run_id = ?", [run_id])
    con.execute("DELETE FROM answers_synth WHERE run_id = ?", [run_id])
    con.execute("DELETE FROM runs WHERE run_id = ?", [run_id])


def list_runs(con: duckdb.DuckDBPyConnection):
    ensure_tables(con)
    return con.execute("""SELECT run_id, created_at, status, template_id, model,
                  n_agents, n_questions, n_answered, n_failed, cost_usd,
                  round(mae, 2) AS mae, round(js_distance, 4) AS js_distance
           FROM runs ORDER BY created_at""").df()
