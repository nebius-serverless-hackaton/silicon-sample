import pytest
from typer.testing import CliRunner

from silicon.cli import app

runner = CliRunner()


@pytest.mark.parametrize(
    "args",
    [[], ["data"], ["storage"], ["llm"], ["run"], ["score"], ["compare"]],
    ids=["root", "data", "storage", "llm", "run", "score", "compare"],
)
def test_help_exits_zero(args):
    result = runner.invoke(app, args + ["--help"])
    assert result.exit_code == 0
