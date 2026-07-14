"""Run the frozen calibrated config against every GSS wave and score each
against that wave's real distributions. Skips waves that already have a
complete scored run with this config, so re-launching resumes after a crash.

Usage: uv run python scripts/waves_sweep.py
"""

import asyncio

from silicon.core.config import get_settings
from silicon.core.storage import duckdb_connection
from silicon.data.conf import load_dataset_config
from silicon.panel.sample import sample_panel
from silicon.run.orchestrate import build_ask_fn, finish, plan_start
from silicon.run.runner import execute
from silicon.score.scoring import score_run

TEMPLATE = "v1_neutral"
AGENTS = 100
SEED = 42
CONCURRENCY = 16
VALID_N_FLOOR = 100


def wave_done(con, year: int, model: str) -> bool:
    return (
        con.execute(
            """SELECT count(*) FROM runs r
               WHERE r.mae IS NOT NULL AND r.status = 'complete'
                 AND r.template_id = ? AND r.model = ? AND r.n_agents = ?
                 AND r.panel_id IN (
                   SELECT DISTINCT p.panel_id FROM panel p
                   JOIN respondents s USING (resp_id) WHERE s.year = ?)""",
            [TEMPLATE, model, AGENTS, year],
        ).fetchone()[0]
        > 0
    )


def wave_qids(con, year: int) -> list[str]:
    rows = con.execute(
        """SELECT DISTINCT qid FROM targets
           WHERE year = ? AND subgroup_dim = 'all' AND valid_n >= ?
           ORDER BY qid""",
        [year, VALID_N_FLOOR],
    ).fetchall()
    return [r[0] for r in rows]


def main() -> None:
    cfg = load_dataset_config()
    model = get_settings().nebius_tokenfactory_model_dev
    con = duckdb_connection()
    years = [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT year FROM targets ORDER BY year"
        ).fetchall()
    ]

    for year in years:
        if wave_done(con, year, model):
            print(f"{year}: already swept - skipping", flush=True)
            continue
        qids = wave_qids(con, year)
        if not qids:
            print(
                f"{year}: no questions with valid_n >= {VALID_N_FLOOR} - skipping",
                flush=True,
            )
            continue

        info = sample_panel(cfg, AGENTS, SEED, year=year)
        plan = plan_start(
            panel_id=info["panel_id"],
            template=TEMPLATE,
            model=model,
            question_set=",".join(qids),
            agents=None,
            temperature=1.0,
            max_tokens=1024,
            concurrency=CONCURRENCY,
            upload=True,
            volunteered="auto",
        )
        ask_fn = build_ask_fn(plan.model, plan.temperature, plan.max_tokens)
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
            )
        )
        finish(plan, "complete")
        summary, _ = score_run(plan.run_id)
        print(
            f"{year}: {len(qids)} questions, MAE {summary['mae']:.1f}pp, "
            f"JS {summary['js_distance']:.3f} (run {plan.run_id})",
            flush=True,
        )
    con.close()
    print("sweep complete", flush=True)


if __name__ == "__main__":
    main()
