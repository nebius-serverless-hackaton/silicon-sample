"""Generate the README evidence figures from the run registry.

Regenerate with:  uv run --with matplotlib python scripts/make_figures.py
Outputs the PNGs embedded in README.md into docs/figures/.
"""

import uuid

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Patch

from silicon.core.storage import duckdb_connection

# run ids of record (see registry): the frozen calibrated configuration and
# the experiments the figures compare
LEADER_2024 = "a6f3f5f7-55c5-4c63-8a59-6fc6f84c4e2e"  # v1_neutral + auto, 11.6pp
CONFIGS = [
    ("one-line persona", "97a3e065-ea99-47af-a7ae-c53b74d907b4"),  # v3_minimal
    ("narrative biography", "a4b13078-4077-47d8-b144-7025fbf36b7e"),  # v2_persona_rich
    ("structured profile card", "10dcd59a-f22b-49a2-b6cd-64383eee2cff"),  # v1_neutral
    ("profile card + calibrated\nanswer presentation", LEADER_2024),
]
MODELS = [
    # name, plain-language tag (405B/70B ≈ 6x, not 4x - keep prose in sync)
    ("Hermes-4-70B", "mid-sized - the winner", LEADER_2024),
    ("Hermes-4-405B", "≈6× larger - no better", "5f6e0559-0fcf-4cbf-a208-51a86aa18d9d"),
    (
        "gpt-oss-120b",
        "reasons step-by-step - 16× the compute",
        "083d318a-f885-49f9-90c5-4006db17700a",
    ),
    (
        "Llama-3.3-70B",
        "same size as the winner",
        "bcaf3af9-4434-4a7b-898d-cab38a811912",
    ),
    ("Qwen3-235B", "≈3× larger", "69308e0a-447f-468c-a69d-b8e295a6ed40"),
]
AREAS = {
    "social issues": [
        "abany",
        "cappun",
        "grass",
        "gunlaw",
        "homosex",
        "prayer",
        "fepol",
    ],
    "government spending": ["natenvir", "natheal", "natrace", "natfare", "nataid"],
    "trust": ["trust", "fair", "helpful", "courts", "conlegis", "confinan", "conarmy"],
    "self-assessment": [
        "happy",
        "health",
        "satfin",
        "polviews",
        "partyid",
        "eqwlth",
        "helppoor",
    ],
}
QUESTION_LABELS = {
    "abany": "abortion: any reason",
    "cappun": "death penalty",
    "grass": "marijuana legalization",
    "gunlaw": "gun permits",
    "homosex": "same-sex relations",
    "prayer": "school prayer ruling",
    "fepol": "men better suited for politics",
    "natenvir": "spending: environment",
    "natheal": "spending: health",
    "natrace": "spending: race equality",
    "natfare": "spending: welfare",
    "nataid": "spending: foreign aid",
    "trust": "people can be trusted",
    "fair": "people: fair or take advantage",
    "helpful": "people: helpful or self-interested",
    "courts": "courts: harshness on crime",
    "conlegis": "confidence: Congress",
    "confinan": "confidence: banks",
    "conarmy": "confidence: military",
    "happy": "general happiness",
    "health": "own health rating",
    "satfin": "financial satisfaction",
    "polviews": "liberal–conservative self-rating",
    "partyid": "party identification",
    "eqwlth": "reduce income differences",
    "helppoor": "government help for the poor",
}

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e5e4e0"
BLUE = "#2a78d6"
AQUA = "#1baf7a"
YELLOW = "#eda100"
GREEN = "#008300"
AREA_COLOR = {
    "social issues": BLUE,
    "government spending": AQUA,
    "trust": YELLOW,
    "self-assessment": GREEN,
}

matplotlib.rcParams.update(
    {
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "text.color": INK,
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK2,
        "xtick.color": INK2,
        "ytick.color": INK2,
        "font.size": 11,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def save(fig, name):
    fig.savefig(f"docs/figures/{name}.png", bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"docs/figures/{name}.png")


def headline(ax, takeaway, subtitle):
    ax.set_title(takeaway, loc="left", fontsize=13, pad=26)
    ax.text(0, 1.03, subtitle, transform=ax.transAxes, color=INK2, fontsize=10)


ANCHOR_RUN = "82fa6bcf-5b76-4011-adca-cee17897b479"
ANCHORS = [
    # label, real poll %, source, qid, panel codes counted as the anchor answer
    ("Ban phones\nduring class", 74, "Pew, Jul 2025", "new:phone-ban-class", (1,)),
    ("Ban phones\nall school day", 44, "Pew, Jul 2025", "new:phone-ban-all-day", (1,)),
    ("AI will mean\nfewer jobs", 64, "Pew, Apr 2025", "new:ai-jobs-20yr", (2,)),
    (
        "Medicare should cover\nweight-loss drugs",
        61,
        "KFF, May 2024",
        "new:glp1-medicare",
        (1,),
    ),
]


def _box(ax, x, y, w, h, title, body, edge="#c9c8c3", title_color=INK):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0,rounding_size=1.6",
            mutation_aspect=2.0,
            facecolor="white",
            edgecolor=edge,
            linewidth=1.3,
        )
    )
    ax.text(
        x + w / 2,
        y + h - 4.5,
        title,
        ha="center",
        va="center",
        fontsize=10,
        color=title_color,
        weight="bold",
    )
    ax.text(
        x + w / 2,
        y + h - 9,
        body,
        ha="center",
        va="top",
        fontsize=8.5,
        color=INK2,
        linespacing=1.4,
    )


def _arrow(ax, p_from, p_to, color=INK2, rad=0.0, lw=1.4):
    ax.annotate(
        "",
        xy=p_to,
        xytext=p_from,
        arrowprops=dict(
            arrowstyle="-|>",
            color=color,
            lw=lw,
            connectionstyle=f"arc3,rad={rad}",
            mutation_scale=13,
        ),
    )


def fig_pipeline():
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    ax.set_xlim(0, 100)
    ax.set_ylim(12, 124)
    ax.axis("off")

    top_y, top_h, w = 72, 30, 22.5
    xs = [0.5, 26, 51.5, 77]
    _box(
        ax,
        xs[0],
        top_y,
        w,
        top_h,
        "1 · Real people",
        "a panel of 100 drawn\nfrom one round of a real\nsurvey (GSS) - nobody\nis invented",
        edge=BLUE,
    )
    _box(
        ax,
        xs[1],
        top_y,
        w,
        top_h,
        "2 · Profile cards",
        "each person's recorded\nfacts become a short\ninstruction card - born\n1964, northeast, married …",
    )
    _box(
        ax,
        xs[2],
        top_y,
        w,
        top_h,
        "3 · AI interview",
        "a language model answers\nevery question as that\nperson - the model itself\nis never changed",
    )
    _box(
        ax,
        xs[3],
        top_y,
        w,
        top_h,
        "4 · Score vs reality",
        "the panel's answer shares\nvs the real survey's -\nthe gap in points, per\nquestion and subgroup",
    )
    mid = top_y + top_h / 2
    for a, b in zip(xs, xs[1:]):
        _arrow(ax, (a + w, mid), (b, mid))

    _arrow(
        ax,
        (xs[3] + w / 2, top_y + top_h),
        (xs[1] + w / 2, top_y + top_h),
        color=YELLOW,
        rad=0.24,
        lw=1.8,
    )
    ax.text(
        (xs[1] + xs[3] + w) / 2,
        117.5,
        "tune only the interview wording, then run again - calibrated on the 2024 round alone",
        ha="center",
        color=INK2,
        fontsize=9,
    )

    bot_y, bot_h, bw = 16, 30, 28
    b5x, b6x = 24, 62
    _box(
        ax,
        b5x,
        bot_y,
        bw,
        bot_h,
        "5 · Verify on unseen data",
        "the frozen setup replays\n50 years of earlier rounds,\nplus fresh 2024–25 polls\n(Pew, KFF) it never saw",
    )
    _box(
        ax,
        b6x,
        bot_y,
        bw,
        bot_h,
        "6 · Ask new questions",
        "unpolled questions answered\nin minutes - trusted only on\ntopics steps 4–5 proved\nreliable",
        edge="#104281",
        title_color="#104281",
    )
    _arrow(ax, (xs[3] + w / 2, top_y), (b5x + bw - 4, bot_y + bot_h), rad=0.2)
    ax.text(
        77,
        56,
        "freeze the\nbest setup",
        ha="center",
        color=INK2,
        fontsize=9,
        linespacing=1.4,
    )
    _arrow(ax, (b5x + bw, bot_y + bot_h / 2), (b6x, bot_y + bot_h / 2))

    headline(
        ax,
        "Calibrate on the past, verify out of sample, only then predict",
        "How the synthetic panel is built, scored against real answers, and promoted to new questions",
    )
    save(fig, "fig_pipeline")


MISS_QID = "new:glp1-medicare"


def fig0_anchors(con):
    labels, real, synth, qids = [], [], [], []
    for label, poll, source, qid, codes in ANCHORS:
        share = con.execute(
            f"""SELECT avg(CASE WHEN code IN {codes} THEN 1.0 ELSE 0 END)
                FROM answers_synth WHERE run_id = ? AND qid = ? AND code IS NOT NULL""",
            [uuid.UUID(ANCHOR_RUN), qid],
        ).fetchone()[0]
        labels.append(f"{label}\n({source})")
        real.append(poll)
        synth.append(share * 100)
        qids.append(qid)

    fig, ax = plt.subplots(figsize=(9, 4.4))
    x = range(len(labels))
    w = 0.38
    synth_colors = [YELLOW if q == MISS_QID else AQUA for q in qids]
    ax.bar([i - w / 2 for i in x], real, w, color=BLUE)
    ax.bar([i + w / 2 for i in x], synth, w, color=synth_colors)
    for i, (rv, sv) in enumerate(zip(real, synth)):
        ax.text(i - w / 2, rv + 1.5, f"{rv:.0f}%", ha="center", color=INK2, fontsize=10)
        ax.text(i + w / 2, sv + 1.5, f"{sv:.0f}%", ha="center", color=INK2, fontsize=10)
    miss_i = qids.index(MISS_QID)
    ax.annotate(
        "the one miss - and calibration had\nflagged this bias before the poll",
        (miss_i + w / 2 + 0.06, 84),
        xytext=(1.62, 90),
        ha="center",
        color=INK2,
        fontsize=9.5,
        arrowprops=dict(
            arrowstyle="->", color=INK2, lw=1.1, connectionstyle="arc3,rad=-0.15"
        ),
    )
    ax.set_xticks(list(x), labels, fontsize=10)
    ax.set_ylim(0, 100)
    ax.set_ylabel("% giving this answer")
    headline(
        ax,
        "Fresh poll questions: three close calls and one instructive miss",
        "The panel answered questions from recent published polls it was never tuned on",
    )
    handles = [
        Patch(color=BLUE, label="real poll"),
        Patch(color=AQUA, label="simulated panel"),
        Patch(color=YELLOW, label="simulated panel - the predicted miss"),
    ]
    ax.legend(handles=handles, frameon=False, loc="upper left", fontsize=10)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    save(fig, "fig0_anchors")


def fig1_history(con):
    df = con.execute(
        """SELECT any_value(re.year) AS year, any_value(r.mae) AS mae
           FROM runs r JOIN panel p ON p.panel_id = r.panel_id
           JOIN respondents re USING (resp_id)
           WHERE r.mae IS NOT NULL AND r.status = 'complete'
             AND r.template_id = 'v1_neutral' AND r.n_agents = 100
             AND r.model = 'NousResearch/Hermes-4-70B'
             AND (r.n_questions >= 9 AND r.question_set != 'all' OR r.run_id = ?)
           GROUP BY r.run_id ORDER BY year""",
        [uuid.UUID(LEADER_2024)],
    ).df()
    fig, ax = plt.subplots(figsize=(9, 4))
    hist = df[df.year < 2024]
    ax.plot(hist.year, hist.mae, "-", color=BLUE, lw=2, zorder=2)
    ax.plot(hist.year, hist.mae, "o", color=BLUE, ms=5, zorder=3)
    lead = df[df.year == 2024]
    ax.plot(lead.year, lead.mae, "o", mfc=SURFACE, mec=YELLOW, mew=2.5, ms=9, zorder=4)
    ax.annotate(
        "2024 - the only year used for tuning",
        (2024, float(lead.mae.iloc[0])),
        xytext=(1994, 22.6),
        color=INK2,
        fontsize=10,
        arrowprops=dict(arrowstyle="-", color=GRID, lw=1.2),
    )
    ax.annotate(
        "all other years were never seen during tuning",
        (1987, 10.4),
        color=INK2,
        fontsize=10,
    )
    ax.axhspan(12, 18, color="#f1f0eb", zorder=0)
    ax.text(1971.8, 12.6, "12–18 point band", color=INK2, fontsize=9)
    ax.set_ylim(0, 25)
    ax.set_ylabel("gap vs real answers (points)")
    headline(
        ax,
        "Tuned on a single year, the panel stays accurate across five decades",
        "Average gap between simulated and real answer percentages, per survey year - lower is better",
    )
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    save(fig, "fig1_history")


INCOME_ORDER = [
    "under $25,000",
    "$25,000 – $49,999",
    "$50,000 – $89,999",
    "$90,000 – $129,999",
    "$130,000 or more",
]
INCOME_SHORT = ["under $25k", "$25–50k", "$50–90k", "$90–130k", "$130k+"]


def fig2_income_gradient(con):
    # eqwlth codes 1-3 = leaning toward "government should reduce income differences"
    real = (
        con.execute(
            """SELECT subgroup_value AS bracket, sum(share) AS share FROM targets
           WHERE qid = 'gss:eqwlth' AND year = 2024
             AND subgroup_dim = 'income' AND code IN (1, 2, 3)
           GROUP BY bracket"""
        )
        .df()
        .set_index("bracket")
        .loc[INCOME_ORDER, "share"]
    )
    answers = con.execute(
        """SELECT a.code, r.* FROM answers_synth a
           JOIN runs ru ON ru.run_id = a.run_id
           JOIN panel p ON p.panel_id = ru.panel_id AND p.agent_id = a.agent_id
           JOIN respondents r USING (resp_id)
           WHERE a.run_id = ? AND a.qid = 'gss:eqwlth' AND a.code IS NOT NULL""",
        [uuid.UUID(LEADER_2024)],
    ).df()
    synth = (
        answers.groupby("income_bracket")["code"]
        .apply(lambda s: s.isin([1, 2, 3]).mean())
        .loc[INCOME_ORDER]
    )

    fig, ax = plt.subplots(figsize=(7.5, 4))
    x = range(len(INCOME_ORDER))
    w = 0.38
    ax.bar(
        [i - w / 2 for i in x],
        real * 100,
        w,
        color=BLUE,
        label="real survey (GSS 2024)",
    )
    ax.bar([i + w / 2 for i in x], synth * 100, w, color=AQUA, label="simulated panel")
    for i, (rv, sv) in enumerate(zip(real, synth)):
        ax.text(
            i - w / 2, rv * 100 + 1.5, f"{rv:.0%}", ha="center", color=INK2, fontsize=10
        )
        ax.text(
            i + w / 2, sv * 100 + 1.5, f"{sv:.0%}", ha="center", color=INK2, fontsize=10
        )
    ax.set_xticks(list(x), INCOME_SHORT)
    ax.set_xlabel("family income")
    ax.set_ylim(0, 100)
    ax.set_ylabel("% leaning toward reducing differences")
    ax.annotate(
        "the one big gap:\nthe panel exaggerates\nthe real downward trend",
        (3 + w / 2 + 0.07, 28),
        xytext=(3.62, 57),
        ha="center",
        color=INK2,
        fontsize=9,
        arrowprops=dict(
            arrowstyle="->", color=INK2, lw=1.1, connectionstyle="arc3,rad=0.15"
        ),
    )
    headline(
        ax,
        "The panel mirrors how opinion shifts with income, not just the national total",
        '"Should government reduce income differences?" - share leaning yes, by family income (2024)',
    )
    ax.legend(frameon=False, loc="upper right", fontsize=10)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    save(fig, "fig2_income_gradient")


def fig3_tuning(con):
    labels, values = [], []
    for label, rid in CONFIGS:
        mae = con.execute(
            "SELECT mae FROM runs WHERE run_id = ?", [uuid.UUID(rid)]
        ).fetchone()[0]
        labels.append(label)
        values.append(mae)
    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    colors = [BLUE] * 3 + ["#104281"]
    bars = ax.barh(range(len(labels)), values, 0.62, color=colors)
    for i, v in enumerate(values):
        ax.text(v + 0.25, i, f"{v:.1f}", va="center", color=INK2, fontsize=10)
    ax.set_yticks(range(len(labels)), labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 20)
    ax.set_xlabel("gap vs real answers (points, lower is better)")
    headline(
        ax,
        "Better interview scripts cut the error by a quarter - the AI model was never changed",
        "Average gap vs the real 2024 survey for four ways of describing the same people",
    )
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    save(fig, "fig3_tuning")


def fig4_per_question(con):
    df = con.execute(
        """SELECT qid, mae FROM scores
           WHERE run_id = ? AND subgroup_dim = 'all' ORDER BY mae""",
        [uuid.UUID(LEADER_2024)],
    ).df()
    var_area = {v: area for area, vs in AREAS.items() for v in vs}
    df["var"] = df.qid.str.removeprefix("gss:")
    df["area"] = df["var"].map(var_area)
    df["label"] = df["var"].map(QUESTION_LABELS)

    fig, ax = plt.subplots(figsize=(9, 7.5))
    ax.barh(range(len(df)), df.mae, 0.65, color=[AREA_COLOR[a] for a in df.area])
    for i, v in enumerate(df.mae):
        ax.text(v + 0.35, i, f"{v:.1f}", va="center", color=INK2, fontsize=9)
    ax.set_yticks(range(len(df)), df["label"], fontsize=9)
    ax.axvline(8, color=INK2, lw=1.2, ls=(0, (4, 3)))
    ax.text(
        8.5,
        6.5,
        "≈8 pp: typical result\nin published research",
        color=INK2,
        fontsize=9,
        va="top",
    )
    ax.set_xlabel("gap vs real answers (points, lower is better)")
    headline(
        ax,
        "Reliable on many topics; weakest on trust in people and institutions",
        "Average gap vs the real 2024 survey, per question - shorter bars mean closer to real answers",
    )
    handles = [plt.Rectangle((0, 0), 1, 1, color=AREA_COLOR[a]) for a in AREAS]
    ax.legend(handles, AREAS.keys(), frameon=False, loc="lower right", fontsize=10)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    save(fig, "fig4_per_question")


def fig5_models(con):
    labels, tags, values = [], [], []
    for label, tag, rid in MODELS:
        mae = con.execute(
            "SELECT mae FROM runs WHERE run_id = ?", [uuid.UUID(rid)]
        ).fetchone()[0]
        labels.append(label)
        tags.append(tag)
        values.append(mae)
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    colors = ["#104281"] + [BLUE] * (len(labels) - 1)
    ax.barh(range(len(labels)), values, 0.62, color=colors)
    for i, (v, tag) in enumerate(zip(values, tags)):
        ax.text(v + 0.25, i, f"{v:.1f}", va="center", color=INK2, fontsize=10)
        ax.text(0.3, i, tag, va="center", ha="left", color="white", fontsize=8.5)
    ax.set_yticks(range(len(labels)), labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 22)
    ax.set_xlabel("gap vs real answers (points, lower is better)")
    headline(
        ax,
        "The most accurate model is not the biggest one",
        "Five AI models given the same people and questions - the 405B model is ≈6× larger than the leader",
    )
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    save(fig, "fig5_models")


def main():
    import pathlib

    pathlib.Path("docs/figures").mkdir(parents=True, exist_ok=True)
    fig_pipeline()
    con = duckdb_connection()
    fig0_anchors(con)
    fig1_history(con)
    fig2_income_gradient(con)
    fig3_tuning(con)
    fig4_per_question(con)
    fig5_models(con)
    con.close()


if __name__ == "__main__":
    main()
