import pytest

from silicon.data.conf import load_dataset_config, load_profile, load_questions

QUESTIONS = load_questions()
PROFILE = load_profile()


@pytest.fixture(
    params=[load_dataset_config, load_profile, load_questions],
    ids=["dataset", "profile", "questions"],
)
def loaded_config(request):
    return request.param()


def test_real_config_files_load(loaded_config):
    assert loaded_config


@pytest.mark.parametrize("q", QUESTIONS, ids=[q.qid for q in QUESTIONS])
def test_question_invariants(q):
    assert q.qid == f"gss:{q.var}"
    assert len(q.text) > 20
    assert len(q.options) >= 2
    codes = [o.code for o in q.options]
    assert len(codes) == len(set(codes))
    assert not set(q.drop_codes) & q.allowed_codes()


@pytest.mark.parametrize("p", PROFILE, ids=[p.var for p in PROFILE])
def test_profile_invariants(p):
    assert p.type in ("int", "category")
    if p.type == "int":
        assert p.recode is None


def test_no_duplicate_question_vars():
    vars_ = [q.var for q in QUESTIONS]
    assert len(vars_) == len(set(vars_))


def test_dataset_config_shape():
    cfg = load_dataset_config()
    assert cfg.dataset == "gss"
    assert cfg.weight_var
    assert cfg.base_year >= 2022
