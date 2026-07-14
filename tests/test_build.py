import pytest

from silicon.data.build import (
    BuildError,
    base_year_warnings,
    build_answers,
    build_respondents,
    validate_codes,
    validate_no_leakage,
    validate_weights,
)
from silicon.data.conf import ProfileField


_KEEP = object()


@pytest.mark.parametrize(
    "bad_weight,expect_problem",
    [(_KEEP, False), (None, True), (0.0, True), (-1.0, True)],
    ids=["valid", "null", "zero", "negative"],
)
def test_validate_weights(df, bad_weight, expect_problem):
    if bad_weight is not _KEEP:
        df = df.copy()
        df.loc[0, "wtssps"] = bad_weight
    assert bool(validate_weights(df, "wtssps")) == expect_problem


def test_leakage_detected(question_factory):
    profile = [ProfileField(var="cappun", field="x", type="category")]
    assert validate_no_leakage(profile, [question_factory()]) != []


@pytest.mark.parametrize(
    "codes,drop_codes,expect_problem",
    [
        ((1, 2), (), False),
        ((1,), (), True),  # code 2 in data but not configured
        ((1,), (2,), False),  # unexpected code silenced via drop_codes
    ],
    ids=["all-mapped", "unmapped-code", "drop-code"],
)
def test_validate_codes(
    df, question_factory, codes, drop_codes, expect_problem
):
    q = question_factory(codes=codes, drop_codes=drop_codes)
    problems = validate_codes(df, [q])
    assert bool(problems) == expect_problem


def test_base_year_warnings(df, question_factory):
    only_2022 = df.copy()
    only_2022["cappun"] = [None, None, 1.0]
    warnings = base_year_warnings(only_2022, [question_factory()], 2024)
    assert "not asked in 2024" in warnings[0]


def test_respondents_required_drop_and_yob(df, cfg):
    profile = [
        ProfileField(var="age", field="age", type="int", required=True),
        ProfileField(var="sex", field="sex", type="category"),
    ]
    labels = {"sex": {1: "male", 2: "female"}}
    out = build_respondents(df, cfg, profile, labels)
    assert len(out) == 2  # row with null age dropped
    assert out.loc[0, "resp_id"] == "gss:2024:1"
    assert out.loc[0, "yob"] == 1984
    assert out.loc[0, "sex"] == "male"


@pytest.mark.parametrize(
    "field,mapping_source",
    [
        ("recode", {1: "recoded-male", 2: "recoded-female"}),
        ("labels", {1: "male", 2: "female"}),
    ],
    ids=["recode-wins", "labels-fallback"],
)
def test_respondents_category_mapping(df, cfg, field, mapping_source):
    recode = mapping_source if field == "recode" else None
    labels = {} if field == "recode" else {"sex": mapping_source}
    profile = [
        ProfileField(var="sex", field="sex", type="category", recode=recode)
    ]
    out = build_respondents(df, cfg, profile, labels)
    assert out.loc[0, "sex"] == mapping_source[1]


def test_answers_long_format_drops_missing_and_drop_codes(
    df, cfg, question_factory
):
    q = question_factory(var="homosex", codes=(1, 2, 3, 4), drop_codes=(5,))
    answers = build_answers(df, cfg, [question_factory(), q])
    cappun = answers[answers.qid == "gss:cappun"]
    homosex = answers[answers.qid == "gss:homosex"]
    assert len(cappun) == 2  # one missing answer dropped
    assert len(homosex) == 2  # code-5 row dropped
    assert set(homosex.code) == {1, 4}


def test_build_error_lists_all_problems():
    with pytest.raises(BuildError) as exc:
        raise BuildError(["a", "b"])
    assert "a" in str(exc.value) and "b" in str(exc.value)
