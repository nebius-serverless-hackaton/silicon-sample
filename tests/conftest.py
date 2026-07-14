import duckdb
import pandas as pd
import pytest

from silicon.data.conf import DatasetConfig, Question, QuestionOption
from silicon.run.registry import ensure_tables


def make_cfg(**overrides):
    defaults = dict(
        dataset="gss",
        release="test",
        dta_path="none.dta",
        encoding="latin1",
        base_year=2024,
        weight_var="wtssps",
        id_vars=["year", "id"],
        extra_vars=[],
        processed_version=1,
    )
    return DatasetConfig(**(defaults | overrides))


def make_question(var="cappun", codes=(1, 2), drop_codes=()):
    return Question(
        qid=f"gss:{var}",
        var=var,
        qtype="single_choice",
        text="Do you favor or oppose?",
        options=[QuestionOption(code=c, text=str(c)) for c in codes],
        drop_codes=list(drop_codes),
    )


@pytest.fixture
def cfg():
    return make_cfg()


@pytest.fixture
def question_factory():
    return make_question


@pytest.fixture
def con():
    return duckdb.connect()


@pytest.fixture
def mem_con(con):
    """In-memory DuckDB connection with the runs/answers_synth/scores tables created."""
    ensure_tables(con)
    return con


@pytest.fixture
def df():
    return pd.DataFrame(
        {
            "year": [2024, 2024, 2022],
            "id": [1, 2, 1],
            "wtssps": [1.1, 0.9, 1.0],
            "age": [40.0, None, 25.0],
            "sex": [1.0, 2.0, 2.0],
            "cappun": [1.0, 2.0, None],
            "homosex": [5.0, 1.0, 4.0],
        }
    )
