import json
import re

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, ValidationError

from silicon.data.conf import Question

_env = Environment(
    loader=FileSystemLoader("prompts"),
    keep_trailing_newline=False,
    undefined=StrictUndefined,
)

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class ParseError(ValueError):
    pass


class AnswerPayload(BaseModel):
    answer: str | int


def render_system(template: str, profile: dict) -> str:
    return _env.get_template(f"{template}.j2").render(**profile).strip()


VOLUNTEERED_STYLES = ("listed", "last-resort", "hidden")


def render_question(question: Question, volunteered_style: str = "listed") -> str:
    """Volunteered options were never read aloud in the real interview; the style controls how faithfully prompts reproduce that."""
    if volunteered_style not in VOLUNTEERED_STYLES:
        raise ValueError(
            f"volunteered_style must be one of {VOLUNTEERED_STYLES}, got {volunteered_style!r}"
        )
    options = [
        o.text
        for o in question.options
        if volunteered_style == "listed" or not o.volunteered
    ]
    last_resort = (
        [o.text for o in question.options if o.volunteered]
        if volunteered_style == "last-resort"
        else []
    )
    return (
        _env.get_template("question.j2")
        .render(text=question.text, options=options, last_resort=last_resort)
        .strip()
    )


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().casefold().rstrip(".")


def parse_answer(raw: str, question: Question) -> int:
    """Maps a model reply back to an option code, tolerating reasoning-model chatter around the JSON."""
    text = THINK_RE.sub("", raw)
    start = text.find("{")
    if start == -1:
        raise ParseError("no JSON object in reply")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as e:
        raise ParseError(f"malformed JSON: {e}") from e
    try:
        payload = AnswerPayload.model_validate(obj)
    except ValidationError as e:
        raise ParseError(f"bad payload shape: {e}") from e

    norm = _normalize(payload.answer)
    for o in question.options:
        if _normalize(o.text) == norm:
            return o.code
    # scale questions ("3", "7 - ...") are commonly answered with the bare number
    if norm.isdigit() and int(norm) in question.allowed_codes():
        return int(norm)
    raise ParseError(f"answer {payload.answer!r} matches no option of {question.qid}")
