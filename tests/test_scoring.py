import uuid

import numpy as np
import pandas as pd
import pytest

from silicon.data.conf import SubgroupDim
from silicon.data.subgroups import assign_subgroups
from silicon.data.targets import compute_targets
from silicon.score.metrics import align_shares, js_distance, mae_pp
from silicon.score.scoring import score_cells, synth_shares

DIMS = [
    SubgroupDim(dim="age_bracket", source="age", bins=[18, 45, float("inf")], labels=["18-44", "45+"]),
    SubgroupDim(dim="region", source="region"),
]


@pytest.mark.parametrize(
    "p,q,expected_mae,expected_js",
    [
        ([0.5, 0.5], [0.5, 0.5], 0.0, 0.0),
        ([1.0, 0.0], [0.0, 1.0], 100.0, 1.0),
        ([0.75, 0.25], [0.5, 0.5], 25.0, 0.2209),
    ],
    ids=["identical", "disjoint", "hand-computed"],
)
def test_metrics(p, q, expected_mae, expected_js):
    p, q = np.array(p), np.array(q)
    assert mae_pp(p, q) == pytest.approx(expected_mae)
    assert js_distance(p, q) == pytest.approx(expected_js, abs=1e-3)


def test_align_fills_missing_codes():
    p, q = align_shares([1, 2, 3], {1: 0.6, 2: 0.4}, {1: 1.0})
    assert p.tolist() == [0.6, 0.4, 0.0]
    assert q.tolist() == [1.0, 0.0, 0.0]


def test_js_nan_on_empty_side():
    assert np.isnan(js_distance(np.array([1.0, 0.0]), np.array([0.0, 0.0])))


def test_assign_subgroups_bins_and_passthrough():
    df = pd.DataFrame({"age": [20, 50, None], "region": ["south", "west", "south"]})
    out = assign_subgroups(df, DIMS)
    assert list(out["age_bracket"].astype("string").fillna("NA")) == ["18-44", "45+", "NA"]
    assert list(out["region"]) == ["south", "west", "south"]


@pytest.fixture
def real_answers():
    return pd.DataFrame({
        "resp_id": ["r1", "r2", "r3", "r4"],
        "weight": [1.0, 1.0, 2.0, 1.0],
        "age": [20, 30, 50, 60],
        "region": ["south", "south", "west", "west"],
        "qid": ["gss:cappun"] * 4,
        "code": [1, 2, 1, 2],
    })


def test_compute_targets_weighted_shares(real_answers):
    targets = compute_targets(real_answers, DIMS)
    overall = targets[targets["subgroup_dim"] == "all"].set_index("code")
    # weighted: code1 = 1+2 = 3 of 5, code2 = 1+1 = 2 of 5
    assert overall.loc[1, "share"] == pytest.approx(0.6)
    assert overall.loc[2, "share"] == pytest.approx(0.4)
    assert (overall["valid_n"] == 4).all()

    young = targets[(targets["subgroup_dim"] == "age_bracket") & (targets["subgroup_value"] == "18-44")]
    assert sorted(young["share"]) == [0.5, 0.5]
    assert (young["valid_n"] == 2).all()


def test_compute_targets_all_years_partitions():
    from silicon.data.targets import compute_targets_all_years

    df = pd.DataFrame({
        "resp_id": ["a", "b", "c", "d"],
        "year": [2022, 2022, 2024, 2024],
        "weight": [1.0] * 4,
        "age": [30, 50, 30, 50],
        "region": ["south"] * 4,
        "qid": ["gss:cappun"] * 4,
        "code": [1, 1, 1, 2],
    })
    targets = compute_targets_all_years(df, DIMS)
    t22 = targets[(targets["year"] == 2022) & (targets["subgroup_dim"] == "all")]
    t24 = targets[(targets["year"] == 2024) & (targets["subgroup_dim"] == "all")]
    assert t22.set_index("code").loc[1, "share"] == pytest.approx(1.0)
    assert t24.set_index("code").loc[1, "share"] == pytest.approx(0.5)
    assert (t22["valid_n"] == 2).all() and (t24["valid_n"] == 2).all()


def test_synth_shares_plain_proportions(real_answers):
    shares = synth_shares(real_answers.drop(columns="weight"), DIMS)
    overall = shares[shares["subgroup_dim"] == "all"].set_index("code")
    assert overall.loc[1, "share"] == pytest.approx(0.5)  # unweighted 2 of 4
    assert (overall["n_synth"] == 4).all()


def make_cells_df(rows, n_col):
    qid, subgroup_dim, subgroup_value, code, share, n = zip(*rows)
    return pd.DataFrame({
        "qid": qid, "subgroup_dim": subgroup_dim, "subgroup_value": subgroup_value,
        "code": code, "share": share, n_col: n,
    })


def test_score_cells_hand_computed():
    targets = make_cells_df(
        [("gss:cappun", "all", "all", 1, 0.5, 200), ("gss:cappun", "all", "all", 2, 0.5, 200)], "valid_n"
    )
    synth = make_cells_df(
        [("gss:cappun", "all", "all", 1, 0.6, 10), ("gss:cappun", "all", "all", 2, 0.4, 10)], "n_synth"
    )
    cells = score_cells(targets, synth, {"gss:cappun": [1, 2]})
    assert len(cells) == 1
    assert cells.iloc[0]["mae"] == pytest.approx(10.0)
    assert not cells.iloc[0]["low_n"]


def test_score_cells_flags_low_n():
    targets = make_cells_df([("q", "all", "all", 1, 1.0, 30)], "valid_n")
    synth = make_cells_df([("q", "all", "all", 1, 1.0, 5)], "n_synth")
    cells = score_cells(targets, synth, {"q": [1]})
    assert cells.iloc[0]["low_n"]


def test_score_cells_skips_empty_synth_cells():
    targets = make_cells_df(
        [("q", "all", "all", 1, 1.0, 100), ("q", "region", "mars", 1, 1.0, 100)], "valid_n"
    )
    synth = make_cells_df([("q", "all", "all", 1, 1.0, 20)], "n_synth")
    cells = score_cells(targets, synth, {"q": [1]})
    assert len(cells) == 1
    assert cells.iloc[0]["subgroup_value"] == "all"


def test_scores_table_rescore_idempotent(mem_con):
    con = mem_con
    run_id = uuid.uuid4()
    cells = pd.DataFrame({
        "run_id": [run_id], "qid": ["q"], "subgroup_dim": ["all"], "subgroup_value": ["all"],
        "mae": [1.0], "js_distance": [0.1], "n_synth": [10], "n_target": [100], "low_n": [False],
    })
    for _ in range(2):
        con.execute("DELETE FROM scores WHERE run_id = ?", [run_id])
        con.register("cells_df", cells)
        con.execute("INSERT INTO scores SELECT * FROM cells_df")
    assert con.execute("SELECT count(*) FROM scores").fetchone()[0] == 1
