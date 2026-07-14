import asyncio
import json
import uuid

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from silicon.api.prospective import add_question, list_questions
from silicon.core.storage import duckdb_connection
from silicon.data.conf import load_questions, load_subgroups
from silicon.run.orchestrate import build_ask_fn, finish, plan_start
from silicon.run.registry import ensure_tables, get_run
from silicon.run.runner import execute
from silicon.score.scoring import synth_shares

app = FastAPI(
    title="silicon-sample",
    description="Synthetic population panel - ask calibrated agents new questions",
)

_tasks: dict[str, asyncio.Task] = {}


class NewQuestion(BaseModel):
    text: str = Field(min_length=10)
    options: list[str] = Field(min_length=2, max_length=10)
    slug: str | None = None


class NewRun(BaseModel):
    qids: list[str] = Field(min_length=1)
    agents: int | None = None


def _clean(d: dict) -> dict:
    """pandas NaN (unpriced cost, unscored mae) is not JSON-serializable."""
    return {
        k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in d.items()
    }


def _best_calibration(con) -> dict | None:
    ensure_tables(con)
    df = con.execute(
        """SELECT run_id, panel_id, template_id, model, temperature, n_agents,
                  round(mae, 2) AS mae_pp, round(js_distance, 4) AS js, config
           FROM runs WHERE mae IS NOT NULL AND status = 'complete'
           ORDER BY mae LIMIT 1"""
    ).df()
    if df.empty:
        return None
    row = df.iloc[0].to_dict()
    row["run_id"] = str(row["run_id"])
    row["panel_id"] = str(row["panel_id"])
    return row


@app.get("/calibration")
def calibration():
    con = duckdb_connection()
    best = _best_calibration(con)
    con.close()
    if not best:
        raise HTTPException(
            404, "no scored calibration runs yet - run `silicon score` first"
        )
    best.pop("config")
    return best


@app.get("/questions")
def questions():
    con = duckdb_connection()
    prospective = list_questions(con)
    con.close()
    return {
        "calibration": [{"qid": q.qid, "text": q.text} for q in load_questions()],
        "prospective": [
            {"qid": q.qid, "text": q.text, "options": [o.text for o in q.options]}
            for q in prospective
        ],
    }


@app.post("/questions", status_code=201)
def create_question(body: NewQuestion):
    con = duckdb_connection()
    try:
        q = add_question(con, body.text, body.options, body.slug)
    except ValueError as e:
        raise HTTPException(409, str(e))
    finally:
        con.close()
    return {
        "qid": q.qid,
        "text": q.text,
        "options": [{"code": o.code, "text": o.text} for o in q.options],
    }


async def _run_plan(plan):
    ask_fn = build_ask_fn(plan.model, plan.temperature, plan.max_tokens)
    status = "complete"
    try:
        await execute(
            plan.con,
            plan.run_id,
            ask_fn,
            plan.tasks,
            plan.systems,
            plan.question_msgs,
            plan.questions,
            concurrency=plan.concurrency,
        )
    except Exception:
        status = "failed"
        raise
    finally:
        finish(plan, status)


@app.post("/runs", status_code=202)
async def create_run_endpoint(body: NewRun):
    # async so plan + task creation happen on the event loop thread - the
    # background execute() then shares the plan's DuckDB connection safely
    con = duckdb_connection()
    best = _best_calibration(con)
    con.close()
    if not best:
        raise HTTPException(
            409, "no calibrated configuration available - score a run first"
        )

    cfg = json.loads(best["config"])
    try:
        plan = plan_start(
            panel_id=best["panel_id"],
            template=best["template_id"],
            model=best["model"],
            question_set=",".join(body.qids),
            agents=body.agents,
            temperature=best["temperature"],
            max_tokens=cfg.get("max_tokens", 1024),
            concurrency=cfg.get("concurrency", 16),
            upload=True,
            volunteered=cfg.get("volunteered", "auto"),
        )
    except RuntimeError as e:
        raise HTTPException(422, str(e))
    task = asyncio.create_task(_run_plan(plan))
    _tasks[str(plan.run_id)] = task
    return {
        "run_id": str(plan.run_id),
        "tasks": len(plan.tasks),
        "panel_id": best["panel_id"],
        "model": best["model"],
        "template": best["template_id"],
        "calibration_run": best["run_id"],
    }


@app.get("/runs/{run_id}")
def run_status(run_id: str):
    con = duckdb_connection()
    ensure_tables(con)
    try:
        run = get_run(con, uuid.UUID(run_id))
    except (RuntimeError, ValueError) as e:
        con.close()
        raise HTTPException(404, str(e))
    answered, failed = con.execute(
        "SELECT count(code), count(*) - count(code) FROM answers_synth WHERE run_id = ?",
        [uuid.UUID(run_id)],
    ).fetchone()
    con.close()
    run["run_id"] = str(run["run_id"])
    run["panel_id"] = str(run["panel_id"])
    run["created_at"] = str(run["created_at"])
    run["progress"] = {
        "answered": answered,
        "failed": failed,
        "total": run["n_agents"] * run["n_questions"],
    }
    return _clean(run)


@app.get("/runs/{run_id}/results")
def run_results(run_id: str):
    rid = uuid.UUID(run_id)
    con = duckdb_connection()
    try:
        run = get_run(con, rid)
    except RuntimeError as e:
        con.close()
        raise HTTPException(404, str(e))

    answers = con.execute(
        """SELECT a.qid, a.code, r.* FROM answers_synth a
           JOIN panel p ON p.panel_id = ? AND p.agent_id = a.agent_id
           JOIN respondents r USING (resp_id)
           WHERE a.run_id = ? AND a.code IS NOT NULL""",
        [run["panel_id"], rid],
    ).df()
    if answers.empty:
        con.close()
        raise HTTPException(
            409, f"run {run_id} has no answers yet (status: {run['status']})"
        )

    option_text = _option_texts(con, answers["qid"].unique().tolist())
    caveat = _best_calibration(con)
    con.close()

    shares = synth_shares(answers, load_subgroups())
    questions_out = []
    for qid, grp in shares.groupby("qid"):
        overall = grp[grp["subgroup_dim"] == "all"]
        subgroups: dict[str, list] = {}
        for dim, dgrp in grp[grp["subgroup_dim"] != "all"].groupby("subgroup_dim"):
            subgroups[dim] = [
                {
                    "value": value,
                    "n": int(vgrp["n_synth"].iloc[0]),
                    "distribution": _dist(vgrp, option_text[qid]),
                }
                for value, vgrp in dgrp.groupby("subgroup_value")
            ]
        questions_out.append(
            {
                "qid": qid,
                "n": int(overall["n_synth"].iloc[0]),
                "distribution": _dist(overall, option_text[qid]),
                "subgroups": subgroups,
            }
        )

    if caveat:
        caveat.pop("config", None)
        caveat = _clean(caveat)
    return {
        "run_id": run_id,
        "status": run["status"],
        "model": run["model"],
        "caveat": {
            "note": "Synthetic estimates from LLM agents calibrated against GSS 2024; "
            "calibration error of the underlying configuration is reported below.",
            "calibration": caveat,
        },
        "questions": questions_out,
    }


def _option_texts(con, qids: list[str]) -> dict[str, dict[int, str]]:
    placeholders = ",".join("?" * len(qids))
    rows = con.execute(
        f"SELECT qid, code, text FROM options WHERE qid IN ({placeholders})", qids
    ).fetchall()
    out: dict[str, dict[int, str]] = {}
    for qid, code, text in rows:
        out.setdefault(qid, {})[code] = text
    for q in list_questions(con):
        if q.qid in qids:
            out[q.qid] = {o.code: o.text for o in q.options}
    return out


def _dist(grp: pd.DataFrame, texts: dict[int, str]) -> list[dict]:
    return [
        {
            "option": texts.get(int(r.code), str(int(r.code))),
            "share": round(float(r.share), 3),
        }
        for r in grp.sort_values("code").itertuples()
    ]
