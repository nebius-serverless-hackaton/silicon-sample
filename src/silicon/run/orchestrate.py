import hashlib
import json
import uuid
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import duckdb

from silicon.core.config import get_settings
from silicon.core.llm import ask, async_client
from silicon.core.storage import duckdb_connection, upload_file
from silicon.data.build import config_hash
from silicon.data.conf import Question, load_questions
from silicon.panel.prompts import render_question, render_system
from silicon.panel.sample import load_profiles
from silicon.run.registry import (
    create_run,
    existing_pairs,
    finalize_run,
    get_run,
    set_status,
)
from silicon.run.runner import pending_tasks


@dataclass
class RunPlan:
    run_id: uuid.UUID
    con: duckdb.DuckDBPyConnection
    tasks: list[tuple[int, str]]
    systems: dict[int, str]
    question_msgs: dict[str, str]
    questions: dict[str, Question]
    model: str
    temperature: float
    max_tokens: int
    concurrency: int
    upload: bool


def _select_questions(question_set: str) -> dict[str, Question]:
    all_q = {q.qid: q for q in load_questions()}
    if question_set == "all":
        return all_q
    qids = [qid.strip() for qid in question_set.split(",")]
    missing = [qid for qid in qids if qid not in all_q]
    if missing:
        # prospective (API-submitted) questions live in DuckDB, not the YAML
        from silicon.api.prospective import get_questions

        con = duckdb_connection()
        all_q |= get_questions(con, missing)
        con.close()
    unknown = [qid for qid in qids if qid not in all_q]
    if unknown:
        raise RuntimeError(f"unknown qid(s) {unknown}; not in config or prospective table")
    return {qid: all_q[qid] for qid in qids}


def _template_hash(template: str) -> str:
    # question.j2 and _contract.j2 shape every prompt, so wording tweaks there
    # must show up in the run's config hash too
    h = hashlib.sha256()
    for name in (template, "question", "_contract"):
        h.update(Path(f"prompts/{name}.j2").read_bytes())
    return h.hexdigest()[:16]


def resolve_style(run_style: str, question: Question) -> str:
    """'auto' defers to the question's calibrated YAML style; anything else is a global override."""
    if run_style == "auto":
        return question.volunteered_style or "listed"
    return run_style


def _render_all(
    template: str, profiles: list[dict], questions: dict[str, Question], volunteered: str
):
    systems = {p["agent_id"]: render_system(template, p) for p in profiles}
    question_msgs = {
        qid: render_question(q, volunteered_style=resolve_style(volunteered, q))
        for qid, q in questions.items()
    }
    return systems, question_msgs


def plan_start(
    panel_id: str,
    template: str,
    model: str | None,
    question_set: str,
    agents: int | None,
    temperature: float,
    max_tokens: int,
    concurrency: int,
    upload: bool,
    volunteered: str = "auto",
) -> RunPlan:
    model = model or get_settings().nebius_tokenfactory_model_dev
    profiles = load_profiles(panel_id, limit=agents)
    questions = _select_questions(question_set)
    systems, question_msgs = _render_all(template, profiles, questions, volunteered)

    con = duckdb_connection()
    config = {
        "max_tokens": max_tokens,
        "concurrency": concurrency,
        "volunteered": volunteered,
        "template_hash": _template_hash(template),
        "data_config_hash": config_hash(),
    }
    run_id = create_run(
        con,
        panel_id=uuid.UUID(panel_id),
        template_id=template,
        model=model,
        temperature=temperature,
        question_set=question_set,
        n_agents=len(profiles),
        n_questions=len(questions),
        config=config,
    )
    tasks = pending_tasks(sorted(systems), sorted(questions), set())
    return RunPlan(
        run_id,
        con,
        tasks,
        systems,
        question_msgs,
        questions,
        model,
        temperature,
        max_tokens,
        concurrency,
        upload,
    )


def plan_resume(run_id: str, concurrency: int | None, upload: bool) -> RunPlan:
    con = duckdb_connection()
    rid = uuid.UUID(run_id)
    run = get_run(con, rid)
    profiles = load_profiles(str(run["panel_id"]), limit=run["n_agents"])
    questions = _select_questions(run["question_set"])
    systems, question_msgs = _render_all(
        run["template_id"], profiles, questions,
        run["config"].get("volunteered", "listed"),
    )

    done = existing_pairs(con, rid)
    tasks = pending_tasks(sorted(systems), sorted(questions), done)
    set_status(con, rid, "running")
    return RunPlan(
        rid,
        con,
        tasks,
        systems,
        question_msgs,
        questions,
        run["model"],
        run["temperature"],
        run["config"]["max_tokens"],
        concurrency or run["config"]["concurrency"],
        upload,
    )


def build_ask_fn(model: str, temperature: float, max_tokens: int):
    client = async_client()
    return partial(
        ask, client, model, temperature=temperature, max_tokens=max_tokens
    )


def finish(plan: RunPlan, status: str) -> dict:
    summary = finalize_run(plan.con, plan.run_id, status)
    if status == "complete" and plan.upload:
        out = Path("data/runs") / str(plan.run_id)
        out.mkdir(parents=True, exist_ok=True)
        parquet = out / "answers.parquet"
        plan.con.execute(
            f"COPY (SELECT * FROM answers_synth WHERE run_id = '{plan.run_id}') TO '{parquet}' (FORMAT PARQUET)"
        )
        run = get_run(plan.con, plan.run_id)
        run["run_id"] = str(run["run_id"])
        run["panel_id"] = str(run["panel_id"])
        run["created_at"] = str(run["created_at"])
        config_path = out / "config.json"
        config_path.write_text(json.dumps(run, indent=1))
        upload_file(parquet, f"runs/{plan.run_id}/answers.parquet")
        upload_file(config_path, f"runs/{plan.run_id}/config.json")
    plan.con.close()
    return summary
