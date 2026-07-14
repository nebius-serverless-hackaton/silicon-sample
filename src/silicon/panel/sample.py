import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from silicon.core.storage import duckdb_connection, upload_file
from silicon.data.conf import DatasetConfig


def bootstrap_indices(weights, n: int, seed: int) -> np.ndarray:
    """Weighted resampling makes the panel self-weighting: agent proportions estimate population shares without carrying weights downstream."""
    p = np.asarray(weights, dtype=float)
    rng = np.random.default_rng(seed)
    return rng.choice(len(p), size=n, replace=True, p=p / p.sum())


def sample_panel(
    cfg: DatasetConfig,
    n: int,
    seed: int,
    panel_id: str | None = None,
    upload: bool = True,
    year: int | None = None,
) -> dict:
    year = year or cfg.base_year
    pid = uuid.UUID(panel_id) if panel_id else uuid.uuid4()
    con = duckdb_connection()
    resp = con.execute(
        "SELECT resp_id, weight FROM respondents WHERE year = ? ORDER BY resp_id",
        [year],
    ).df()
    if resp.empty:
        raise RuntimeError(
            f"no respondents for wave {year} - run `silicon data build` first"
        )

    idx = bootstrap_indices(resp["weight"], n, seed)
    panel = pd.DataFrame(
        {
            "panel_id": str(pid),
            "agent_id": range(n),
            "resp_id": resp["resp_id"].iloc[idx].to_numpy(),
            "seed": seed,
            "created_at": datetime.now(timezone.utc),
        }
    )

    con.execute(
        "CREATE TABLE IF NOT EXISTS panel (panel_id UUID, agent_id INTEGER, resp_id VARCHAR, seed INTEGER, created_at TIMESTAMP)"
    )
    con.execute("DELETE FROM panel WHERE panel_id = ?", [pid])
    con.register("panel_df", panel)
    con.execute(
        "INSERT INTO panel SELECT CAST(panel_id AS UUID), agent_id, resp_id, seed, created_at FROM panel_df"
    )

    out = Path("data/panels")
    out.mkdir(parents=True, exist_ok=True)
    parquet = out / f"{pid}.parquet"
    # COPY cannot bind the target filename as a parameter; pid is a validated UUID
    con.execute(
        f"COPY (SELECT * FROM panel WHERE panel_id = '{pid}') TO '{parquet}' (FORMAT PARQUET)"
    )
    n_unique = con.execute(
        "SELECT count(DISTINCT resp_id) FROM panel WHERE panel_id = ?", [pid]
    ).fetchone()[0]
    con.close()

    if upload:
        upload_file(parquet, f"panels/{pid}.parquet")

    return {
        "panel_id": str(pid),
        "agents": n,
        "unique_respondents": n_unique,
        "seed": seed,
    }


def delete_panel(panel_id: str, force: bool = False) -> None:
    from silicon.run.registry import ensure_tables

    pid = uuid.UUID(panel_id)
    con = duckdb_connection()
    ensure_tables(con)
    refs = con.execute(
        "SELECT count(*) FROM runs WHERE panel_id = ?", [pid]
    ).fetchone()[0]
    if refs and not force:
        con.close()
        raise RuntimeError(
            f"panel {pid} is referenced by {refs} run(s) - delete them first or use --force"
        )
    con.execute("DELETE FROM panel WHERE panel_id = ?", [pid])
    con.close()
    Path(f"data/panels/{pid}.parquet").unlink(missing_ok=True)


def list_panels() -> pd.DataFrame:
    con = duckdb_connection()
    try:
        return con.execute("""
            SELECT panel_id, any_value(r.year) AS year, count(*) AS agents,
                   count(DISTINCT resp_id) AS unique_respondents,
                   any_value(seed) AS seed, min(p.created_at) AS created_at
            FROM panel p JOIN respondents r USING (resp_id)
            GROUP BY panel_id ORDER BY created_at
        """).df()
    finally:
        con.close()


def load_profiles(panel_id: str, limit: int | None = None) -> list[dict]:
    con = duckdb_connection()
    sql = """
        SELECT p.agent_id, r.*
        FROM panel p JOIN respondents r USING (resp_id)
        WHERE p.panel_id = ?
        ORDER BY p.agent_id
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    df = con.execute(sql, [uuid.UUID(panel_id)]).df()
    con.close()
    if df.empty:
        raise RuntimeError(
            f"panel {panel_id!r} not found - run `silicon panel sample` first"
        )
    return [
        {k: (None if pd.isna(v) else v) for k, v in row.items()}
        for row in df.to_dict(orient="records")
    ]
