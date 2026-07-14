import typer

app = typer.Typer(help="Synthetic population panel - pipeline CLI")
storage_app = typer.Typer(help="Nebius Object Storage checks")
llm_app = typer.Typer(help="Nebius inference checks")
data_app = typer.Typer(help="GSS dataset pipeline: extract, build")
panel_app = typer.Typer(help="Synthetic panel: sample agents, preview prompts")
run_app = typer.Typer(help="Inference runs: batch-ask the panel, resume, inspect")
app.add_typer(storage_app, name="storage")
app.add_typer(llm_app, name="llm")
app.add_typer(data_app, name="data")
app.add_typer(panel_app, name="panel")
app.add_typer(run_app, name="run")


def _execute_plan(plan) -> str:
    import asyncio

    from rich.progress import Progress

    from silicon.run.orchestrate import build_ask_fn
    from silicon.run.runner import execute

    if not plan.tasks:
        typer.echo("nothing to do - all tasks already answered")
        return "complete"
    ask_fn = build_ask_fn(plan.model, plan.temperature, plan.max_tokens)
    status = "complete"
    with Progress() as progress:
        bar = progress.add_task(f"run {plan.run_id}", total=len(plan.tasks))
        try:
            asyncio.run(
                execute(
                    plan.con,
                    plan.run_id,
                    ask_fn,
                    plan.tasks,
                    plan.systems,
                    plan.question_msgs,
                    plan.questions,
                    concurrency=plan.concurrency,
                    on_result=lambda r: progress.advance(bar),
                )
            )
        except KeyboardInterrupt:
            status = "interrupted"
    return status


def _report(summary: dict) -> None:
    typer.echo(
        f"{summary['status']} - answered {summary['answered']}, failed {summary['failed']}, "
        f"tokens {summary['prompt_tokens']}+{summary['completion_tokens']}"
        + (
            f", cost ${summary['cost_usd']:.4f}"
            if summary["cost_usd"] is not None
            else ""
        )
    )
    if summary["status"] == "interrupted":
        typer.secho(
            f"resume with: silicon run resume {summary['run_id']}",
            fg=typer.colors.YELLOW,
        )


@run_app.command("start")
def run_start(
    panel_id: str = typer.Option(..., help="Panel to run (see `silicon panel list`)"),
    template: str = typer.Option("v1_neutral", help="Prompt template name"),
    model: str = typer.Option(None, help="Model id; defaults to the dev model"),
    qids: str = typer.Option("all", help="Comma-separated qids, or 'all'"),
    agents: int = typer.Option(None, help="Limit to the first N agents (smoke runs)"),
    concurrency: int = typer.Option(16, help="Max in-flight requests"),
    temperature: float = typer.Option(1.0, help="Sampling temperature"),
    max_tokens: int = typer.Option(1024, help="Completion token cap per request"),
    upload: bool = typer.Option(
        True, help="Upload results to object storage on completion"
    ),
    volunteered: str = typer.Option(
        "auto",
        help="Volunteered options in prompts: auto (per-question YAML) | listed | last-resort | hidden",
    ),
) -> None:
    """Start a new inference run of panel agents x questions."""
    from silicon.run.orchestrate import finish, plan_start

    plan = plan_start(
        panel_id,
        template,
        model,
        qids,
        agents,
        temperature,
        max_tokens,
        concurrency,
        upload,
        volunteered=volunteered,
    )
    typer.echo(
        f"run {plan.run_id}: {len(plan.tasks)} tasks ({len(plan.systems)} agents x {len(plan.questions)} questions)"
    )
    status = _execute_plan(plan)
    _report(finish(plan, status))


@run_app.command("resume")
def run_resume(
    run_id: str = typer.Argument(..., help="Run to resume"),
    concurrency: int = typer.Option(None, help="Override stored concurrency"),
    upload: bool = typer.Option(
        True, help="Upload results to object storage on completion"
    ),
) -> None:
    """Fill the unanswered gaps of an interrupted or crashed run."""
    from silicon.run.orchestrate import finish, plan_resume

    plan = plan_resume(run_id, concurrency, upload)
    typer.echo(f"run {plan.run_id}: {len(plan.tasks)} tasks remaining")
    status = _execute_plan(plan)
    _report(finish(plan, status))


@run_app.command("delete")
def run_delete(
    run_id: str = typer.Argument(..., help="Run to delete (registry, answers, scores)"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation"),
) -> None:
    """Delete a run and all its local artifacts (S3 objects are kept)."""
    import shutil
    import uuid as _uuid

    from silicon.core.storage import duckdb_connection
    from silicon.run.registry import delete_run

    if not yes:
        typer.confirm(f"delete run {run_id} and its answers/scores?", abort=True)
    rid = _uuid.UUID(run_id)
    con = duckdb_connection()
    delete_run(con, rid)
    con.close()
    shutil.rmtree(f"data/runs/{rid}", ignore_errors=True)
    shutil.rmtree(f"data/reports/{rid}", ignore_errors=True)
    typer.echo(f"deleted run {rid}")


@panel_app.command("delete")
def panel_delete(
    panel_id: str = typer.Argument(..., help="Panel to delete"),
    force: bool = typer.Option(False, help="Delete even if runs reference this panel"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation"),
) -> None:
    """Delete a panel and its local parquet (S3 objects are kept)."""
    from silicon.panel.sample import delete_panel

    if not yes:
        typer.confirm(f"delete panel {panel_id}?", abort=True)
    delete_panel(panel_id, force=force)
    typer.echo(f"deleted panel {panel_id}")


@run_app.command("list")
def run_list() -> None:
    """List all runs with status and totals."""
    from silicon.core.storage import duckdb_connection
    from silicon.run.registry import list_runs

    con = duckdb_connection()
    df = list_runs(con)
    con.close()
    if df.empty:
        typer.echo("no runs yet - run `silicon run start`")
        return
    typer.echo(df.to_string(index=False))


@run_app.command("show")
def run_show(run_id: str = typer.Argument(..., help="Run to inspect")) -> None:
    """Show one run's config and per-question answer counts."""
    import json
    import uuid as _uuid

    from silicon.core.storage import duckdb_connection
    from silicon.run.registry import get_run

    con = duckdb_connection()
    run = get_run(con, _uuid.UUID(run_id))
    for k, v in run.items():
        typer.echo(f"{k}: {json.dumps(v) if isinstance(v, dict) else v}")
    per_q = con.execute(
        """SELECT qid, count(code) AS answered, count(*) - count(code) AS failed,
                  round(avg(retries), 2) AS avg_retries
           FROM answers_synth WHERE run_id = ? GROUP BY qid ORDER BY qid""",
        [_uuid.UUID(run_id)],
    ).df()
    con.close()
    if not per_q.empty:
        typer.echo(per_q.to_string(index=False))


@panel_app.command("sample")
def panel_sample(
    n: int = typer.Option(100, help="Number of agents to bootstrap"),
    seed: int = typer.Option(42, help="Random seed for reproducibility"),
    panel_id: str = typer.Option(None, help="Panel id; defaults to a new UUID"),
    upload: bool = typer.Option(True, help="Upload panel parquet to object storage"),
    year: int = typer.Option(
        None, help="GSS wave to sample from; defaults to config base_year"
    ),
) -> None:
    """Bootstrap a weighted panel of agents from one GSS wave's respondents."""
    from silicon.data.conf import load_dataset_config
    from silicon.panel.sample import sample_panel

    info = sample_panel(
        load_dataset_config(),
        n=n,
        seed=seed,
        panel_id=panel_id,
        upload=upload,
        year=year,
    )
    typer.echo(
        f"OK - panel {info['panel_id']}: {info['agents']} agents "
        f"from {info['unique_respondents']} unique respondents (seed {info['seed']})"
    )


@panel_app.command("list")
def panel_list() -> None:
    """List sampled panels with their sizes and seeds."""
    from silicon.panel.sample import list_panels

    df = list_panels()
    if df.empty:
        typer.echo("no panels yet - run `silicon panel sample`")
        return
    typer.echo(df.to_string(index=False))


@panel_app.command("render")
def panel_render(
    panel_id: str = typer.Option(..., help="Panel to preview"),
    template: str = typer.Option(
        "v1_neutral", help="Prompt template name (file in prompts/)"
    ),
    agents: int = typer.Option(1, help="How many agents to preview"),
    qid: str = typer.Option(
        "gss:cappun", help="Question to render alongside the persona"
    ),
    volunteered: str = typer.Option(
        "auto",
        help="Volunteered options in prompts: auto (per-question YAML) | listed | last-resort | hidden",
    ),
) -> None:
    """Preview rendered system prompts and a question message for a few agents."""
    from silicon.data.conf import load_questions
    from silicon.panel.prompts import render_question, render_system
    from silicon.panel.sample import load_profiles

    question = next(q for q in load_questions() if q.qid == qid)
    for profile in load_profiles(panel_id, limit=agents):
        typer.secho(
            f"--- agent {profile['agent_id']} ({profile['resp_id']}) ---",
            fg=typer.colors.CYAN,
        )
        typer.echo(render_system(template, profile))
        typer.echo()
    typer.secho(f"--- question {qid} ---", fg=typer.colors.CYAN)
    typer.echo(render_question(question, volunteered_style=volunteered))


@data_app.command("extract")
def data_extract(
    upload: bool = typer.Option(
        True, help="Upload extracted artifacts to object storage"
    ),
) -> None:
    """Pull configured columns out of the raw GSS .dta into extracted parquet."""
    from silicon.data.conf import (
        load_dataset_config,
        load_profile,
        load_questions,
    )
    from silicon.data.extract import run_extract

    path = run_extract(
        load_dataset_config(), load_profile(), load_questions(), upload=upload
    )
    typer.echo(f"OK - extracted to {path}")


@data_app.command("build")
def data_build(
    upload: bool = typer.Option(True, help="Upload processed tables to object storage"),
) -> None:
    """Recode the extract into modeling tables (DuckDB + parquet) with validation."""
    from silicon.data.build import run_build
    from silicon.data.conf import (
        load_dataset_config,
        load_profile,
        load_questions,
    )

    manifest = run_build(
        load_dataset_config(), load_profile(), load_questions(), upload=upload
    )
    for name, n in manifest["rows"].items():
        typer.echo(f"{name}: {n} rows")
    for w in manifest["warnings"]:
        typer.secho(f"warning: {w}", fg=typer.colors.YELLOW)
    typer.echo(
        f"OK - processed v={manifest['version']} (config {manifest['config_hash']})"
    )


@data_app.command("targets")
def data_targets(
    upload: bool = typer.Option(True, help="Upload targets parquet to object storage"),
) -> None:
    """Compute weighted real answer distributions per question and subgroup."""
    from silicon.data.conf import load_dataset_config, load_subgroups
    from silicon.data.targets import build_targets

    summary = build_targets(load_dataset_config(), load_subgroups(), upload=upload)
    typer.echo(
        f"OK - {summary['rows']} target rows: {summary['years']} waves, "
        f"{summary['questions']} questions, {summary['cells']} cells "
        f"({summary['thin_cells']} thin, valid_n < 60)"
    )


@app.command("score")
def score(
    run_id: str = typer.Argument(..., help="Run to score against targets"),
    upload: bool = typer.Option(True, help="Upload scores parquet to object storage"),
) -> None:
    """Score a run's answers against real weighted targets (MAE pp + JS distance)."""
    import uuid as _uuid

    from silicon.score.scoring import score_run

    summary, cells = score_run(_uuid.UUID(run_id), upload=upload)
    overall = cells[cells["subgroup_dim"] == "all"].sort_values("mae", ascending=False)
    typer.echo(
        overall[["qid", "mae", "js_distance", "n_synth", "n_target", "low_n"]]
        .round({"mae": 1, "js_distance": 3})
        .to_string(index=False)
    )
    by_dim = (
        cells.groupby("subgroup_dim", as_index=False)
        .agg(mean_mae=("mae", "mean"), cells=("mae", "count"), low_n=("low_n", "sum"))
        .round({"mean_mae": 1})
    )
    typer.echo(by_dim.to_string(index=False))
    typer.echo(
        f"OK - run {summary['run_id']}: MAE {summary['mae']:.1f}pp, "
        f"JS {summary['js_distance']:.3f} over {summary['questions']} questions "
        f"({summary['low_n_cells']}/{summary['cells']} low-n cells)"
    )


@app.command("compare")
def compare(
    run_ids: list[str] = typer.Argument(
        None, help="Runs to compare; default: all scored runs"
    ),
) -> None:
    """Side-by-side scored runs, best MAE first."""
    import uuid as _uuid

    from silicon.core.storage import duckdb_connection
    from silicon.run.registry import ensure_tables

    con = duckdb_connection()
    ensure_tables(con)
    sql = """SELECT run_id, template_id, model, temperature, n_agents, n_questions,
                    n_failed, round(mae, 2) AS mae_pp, round(js_distance, 4) AS js, cost_usd
             FROM runs WHERE mae IS NOT NULL"""
    params = []
    if run_ids:
        sql += f" AND run_id IN ({','.join('?' * len(run_ids))})"
        params = [_uuid.UUID(r) for r in run_ids]
    df = con.execute(sql + " ORDER BY mae", params).df()
    con.close()
    if df.empty:
        typer.echo("no scored runs - run `silicon score <run_id>` first")
        return
    typer.echo(df.to_string(index=False))


@app.command("api")
def api(
    host: str = typer.Option("127.0.0.1", help="Bind address"),
    port: int = typer.Option(8000, help="Port"),
) -> None:
    """Serve the FastAPI app: submit prospective questions, run them, read results."""
    import uvicorn

    uvicorn.run("silicon.api.app:app", host=host, port=port)


@storage_app.command("check")
def storage_check() -> None:
    """List and round-trip a small object through the configured Nebius bucket."""
    from silicon.core.storage import check_storage

    typer.echo(check_storage())


@llm_app.command("check")
def llm_check(
    model: str = typer.Option(None, help="Override the dev model id for this check"),
) -> None:
    """Send one completion to the Nebius inference endpoint."""
    from silicon.core.llm import check_llm_roundtrip

    typer.echo(check_llm_roundtrip(model=model))


if __name__ == "__main__":
    app()
