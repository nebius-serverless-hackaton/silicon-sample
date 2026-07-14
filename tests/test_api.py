import pytest
from fastapi.testclient import TestClient

from silicon.api.prospective import add_question, get_questions, list_questions
from silicon.core.config import get_settings


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "test.duckdb"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def api(tmp_db):
    from silicon.api.app import app

    return TestClient(app)


def test_add_and_list_prospective(con):
    q = add_question(con, "Do you support a four-day working week?", ["Support", "Oppose", "Not sure"])
    assert q.qid == "new:do-you-support-a-four-day-workin"
    assert [o.code for o in q.options] == [1, 2, 3]
    assert q.allowed_codes() == {1, 2, 3}

    listed = list_questions(con)
    assert len(listed) == 1
    assert get_questions(con, [q.qid])[q.qid].text == q.text


def test_duplicate_slug_rejected(con):
    add_question(con, "Some question about things?", ["A", "B"], slug="things")
    with pytest.raises(ValueError):
        add_question(con, "Another question entirely?", ["C", "D"], slug="things")


def test_api_create_and_list_question(api):
    resp = api.post("/questions", json={"text": "Should tips be tax free?", "options": ["Yes", "No"], "slug": "tips"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["qid"] == "new:tips"
    assert body["options"] == [{"code": 1, "text": "Yes"}, {"code": 2, "text": "No"}]

    listed = api.get("/questions").json()
    assert any(q["qid"] == "new:tips" for q in listed["prospective"])
    assert any(q["qid"] == "gss:cappun" for q in listed["calibration"])


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"text": "short", "options": ["A", "B"]}, 422),
        ({"text": "Long enough question text?", "options": ["only-one"]}, 422),
    ],
    ids=["text-too-short", "one-option"],
)
def test_api_question_validation(api, payload, expected):
    assert api.post("/questions", json=payload).status_code == expected


@pytest.mark.parametrize(
    "method,path,json_body,expected",
    [
        ("get", "/calibration", None, 404),
        ("post", "/runs", {"qids": ["new:whatever"]}, 409),
        ("get", "/runs/00000000-0000-0000-0000-000000000000", None, 404),
    ],
    ids=["calibration-empty-db", "run-without-calibration", "run-status-missing"],
)
def test_api_error_statuses(api, method, path, json_body, expected):
    resp = getattr(api, method)(path, json=json_body) if json_body else getattr(api, method)(path)
    assert resp.status_code == expected
