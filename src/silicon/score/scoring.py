import uuid
from pathlib import Path

import duckdb
import pandas as pd

from silicon.core.storage import duckdb_connection, upload_file
from silicon.data.conf import SubgroupDim, load_subgroups
from silicon.data.subgroups import assign_subgroups
from silicon.run.registry import ensure_tables, get_run
from silicon.score.metrics import align_shares, js_distance, mae_pp


def synth_shares(df: pd.DataFrame, dims: list[SubgroupDim]) -> pd.DataFrame:
    """Plain proportions: the panel is weight-bootstrapped, so agents are self-weighting."""
    df = assign_subgroups(df, dims)

    def shares(sub: pd.DataFrame, dim: str, value: str) -> pd.DataFrame:
        g = sub.groupby(["qid", "code"], as_index=False).agg(n=("code", "count"))
        g["share"] = g["n"] / g.groupby("qid")["n"].transform("sum")
        g["n_synth"] = g.groupby("qid")["n"].transform("sum")
        g["subgroup_dim"] = dim
        g["subgroup_value"] = value
        return g[["qid", "subgroup_dim", "subgroup_value", "code", "share", "n_synth"]]

    frames = [shares(df, "all", "all")]
    for d in dims:
        for value, sub in df.groupby(d.dim, observed=True):
            frames.append(shares(sub, d.dim, str(value)))
    return pd.concat(frames, ignore_index=True)


def score_cells(
    targets: pd.DataFrame,
    synth: pd.DataFrame,
    option_codes: dict[str, list[int]],
    valid_n_floor: int = 60,
    min_synth: int = 10,
) -> pd.DataFrame:
    synth_idx = {
        key: dict(zip(grp["code"], grp["share"]))
        for key, grp in synth.groupby(["qid", "subgroup_dim", "subgroup_value"])
    }
    synth_n = {
        key: int(grp["n_synth"].iloc[0])
        for key, grp in synth.groupby(["qid", "subgroup_dim", "subgroup_value"])
    }
    rows = []
    for key, grp in targets.groupby(["qid", "subgroup_dim", "subgroup_value"]):
        qid, dim, value = key
        s = synth_idx.get(key)
        if not s:
            continue  # no agents landed in this cell (small panel or empty subgroup)
        t = dict(zip(grp["code"], grp["share"]))
        n_target = int(grp["valid_n"].iloc[0])
        n_syn = synth_n[key]
        p, q = align_shares(option_codes[qid], t, s)
        rows.append(
            {
                "qid": qid,
                "subgroup_dim": dim,
                "subgroup_value": value,
                "mae": mae_pp(p, q),
                "js_distance": js_distance(p, q),
                "n_synth": n_syn,
                "n_target": n_target,
                "low_n": n_target < valid_n_floor or n_syn < min_synth,
            }
        )
    return pd.DataFrame(rows)


def score_run(
    run_id: uuid.UUID,
    con: duckdb.DuckDBPyConnection | None = None,
    upload: bool = True,
) -> tuple[dict, pd.DataFrame]:
    own_con = con is None
    con = con or duckdb_connection()
    ensure_tables(con)
    run = get_run(con, run_id)

    answers = con.execute(
        """SELECT a.qid, a.code, r.* FROM answers_synth a
           JOIN panel p ON p.panel_id = ? AND p.agent_id = a.agent_id
           JOIN respondents r USING (resp_id)
           WHERE a.run_id = ? AND a.code IS NOT NULL""",
        [run["panel_id"], run_id],
    ).df()
    if answers.empty:
        raise RuntimeError(f"run {run_id} has no parsed answers to score")
    # a panel is bootstrapped from a single wave; that wave's real
    # distributions are the only valid comparison targets
    panel_year = int(answers["year"].iloc[0])
    targets = con.execute("SELECT * FROM targets WHERE year = ?", [panel_year]).df()
    if targets.empty:
        raise RuntimeError(
            f"no targets for wave {panel_year} - run `silicon data targets` (multi-year) first"
        )
    targets = targets[targets["qid"].isin(answers["qid"].unique())]
    option_codes = {
        qid: grp["code"].tolist()
        for qid, grp in con.execute("SELECT qid, code FROM options ORDER BY qid, ord")
        .df()
        .groupby("qid")
    }

    dims = load_subgroups()
    cells = score_cells(targets, synth_shares(answers, dims), option_codes)
    cells.insert(0, "run_id", run_id)

    con.execute("DELETE FROM scores WHERE run_id = ?", [run_id])
    con.register("cells_df", cells)
    con.execute("INSERT INTO scores SELECT * FROM cells_df")

    overall = cells[cells["subgroup_dim"] == "all"]
    mae = float(overall["mae"].mean())
    js = float(overall["js_distance"].mean())
    con.execute(
        "UPDATE runs SET mae = ?, js_distance = ? WHERE run_id = ?", [mae, js, run_id]
    )

    out_dir = Path("data/reports") / str(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet = out_dir / "scores.parquet"
    con.execute(
        f"COPY (SELECT * FROM scores WHERE run_id = '{run_id}') TO '{parquet}' (FORMAT PARQUET)"
    )
    if upload:
        upload_file(parquet, f"reports/{run_id}/scores.parquet")

    summary = {
        "run_id": str(run_id),
        "target_year": panel_year,
        "mae": mae,
        "js_distance": js,
        "questions": int(overall["qid"].nunique()),
        "cells": len(cells),
        "low_n_cells": int(cells["low_n"].sum()),
    }
    if own_con:
        con.close()
    return summary, cells
