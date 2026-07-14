# Architecture

*Internal design doc: how the system is put together. For what it found, start from the [README](../../README.md); the runner has [its own doc](RUNNER.md).*

## Overview & stack

A CLI pipeline (`silicon <stage>` commands) plus a small FastAPI read/submit API. DuckDB is the working store and run registry; every artifact is mirrored to object storage as Parquet; prompts are Jinja2 text files versioned in-repo.

| Concern | Choice |
|---|---|
| Language | Python 3.12, `uv` for env/deps |
| CLI | Typer (`silicon <stage>` commands) |
| API | FastAPI + uvicorn |
| Analytics store | DuckDB (local file `data/panel.duckdb`) + Parquet |
| Object storage | Nebius Object Storage via S3 API (`boto3` / DuckDB `httpfs` with `endpoint_url`) |
| Inference | OpenAI SDK pointed at Nebius endpoint (`base_url` + `NEBIUS_TOKENFACTORY_API_KEY`), model name from env |
| Prompt templates | Jinja2 files versioned in-repo |
| Validation | Pydantic (strict JSON answer contract, config) |

```
                 ┌────────────────────────────────────────────┐
 GSS raw data ──▶│ ingest ──▶ preprocess ──▶ targets          │
                 └───────────────┬────────────────────────────┘
                                 ▼
                 ┌────────────────────────────────────────────┐
                 │ sample (bootstrap panel) ──▶ render prompts │
                 └───────────────┬────────────────────────────┘
                                 ▼
                 ┌────────────────────────────────────────────┐
                 │ run (async batch → LLM API) ──▶ parse/save  │
                 │ score (MAE + JS distance vs targets)        │
                 └───────────────┬────────────────────────────┘
                                 ▼
                 ┌────────────────────────────────────────────┐
                 │ FastAPI: submit new questions, read results │
                 └────────────────────────────────────────────┘
```

## Storage

Three immutable data layers, so recode iteration never re-parses the 570MB `.dta`; plus per-run artifacts. Bucket layout (`silicon-sample`):

```
raw/gss/<release>/GSS_stata.zip           # original zip, exactly as downloaded
raw/gss/<release>/manifest.json           # source URL, sha256, size, downloaded_at
extracted/gss/<release>/extract.parquet   # selected columns only, original codes
processed/v=<n>/...                       # respondents/questions/options/answers_real/targets + manifest
runs/<run_id>/config.json                 # full run config snapshot
runs/<run_id>/answers.parquet             # validated agent answers
reports/<run_id>/scores.parquet           # calibration scores
```

`processed/v=N` is bumped manually when schema or recodes change meaningfully; the manifest records the config hash so any run is traceable to exact inputs. DuckDB reads/writes object storage directly via `httpfs`, so "sync" is mostly `COPY ... TO 's3://...'`; the local `.duckdb` file is a cache/workspace, object storage is the source of truth.

## Data layer

### Source file

| | |
|---|---|
| File | GSS Cross-Sectional Cumulative Data, 1972–2024 (Release 3a, July 2026) |
| URL | `https://gss.norc.org/content/dam/gss/get-the-data/documents/stata/GSS_stata.zip` |
| Format | Stata `.dta` inside zip - 6,943 variables × 75,699 respondents, 570MB |
| Encoding | **latin-1, not UTF-8** - `pyreadstat.read_dta(..., encoding='latin1')`; the default UTF-8 read crashes on value labels |
| Auth | None - direct public download (zip is 47MB) |
| Per-year alternative | `.../documents/stata/<YEAR>_stata.zip` (fallback if cumulative has issues) |

GSS facts that shape the design:

- **Split-ballot design.** Each respondent is asked only a subset of questions, so the answers table is inherently sparse - long format is mandatory, and per-question valid N is much smaller than the round's total N.
- **Weights are required.** Raw counts do not represent the US population. Verified against the file: `wtssps` ("person post-stratification weight") has 100% coverage in every round 1972–2024 - one weight variable for all years, no per-era switching. Extraction still fails loudly if it's absent.
- **2021 methodology break.** COVID forced a switch from face-to-face to web/address-based sampling; 2021+ vs earlier comparisons carry a mode caveat.
- **Coded values.** Answers are numeric codes with Stata value labels (e.g. `abany`: `{1: 'yes', 2: 'no'}`). Codes are the stable join key; curated YAML maps code → exact response-option text.
- **Missing codes.** GSS uses Stata *tagged missing* values (`.d` don't know, `.i` not asked, `.n` no answer, `.r` refused, …); pyreadstat maps all of these to NaN by default, so valid answers are simply the non-null numeric codes.

### Config files

**`config/gss_dataset.yaml`** - technical settings:

```yaml
dataset: gss
release: r3-2026-03
source_url: https://gss.norc.org/content/dam/gss/get-the-data/documents/stata/GSS_stata.zip
base_year: 2024
weight_var: wtssps          # verified: 100% coverage 1972-2024
encoding: latin1            # verified: UTF-8 read crashes on value labels
id_vars: [year, id]
extra_vars: [ballot]        # kept for diagnostics, not in profiles
```

**`config/gss_profile.yaml`** - demographics → persona fields, one entry per attribute with a harmonized name and recode:

```yaml
- var: age
  field: yob                # rendered as year of birth: base_year - age
  type: int
- var: degree
  field: education
  type: category
  recode:                   # 5 levels -> 3, example of category collapse
    {0: no high school diploma, 1: high school, 2: high school,
     3: college degree, 4: college degree}
- var: realinc
  field: income_bracket
  type: binned
  bins: [0, 25000, 50000, 90000, .inf]
  labels: [under $25k, $25k–$50k, $50k–$90k, over $90k]
# + sex, race, region, wrkstat, marital, childs, relig, attend
```

2024 profile coverage: region/degree/wrkstat/marital ≥99.5%, sex/race/relig/attend/childs ≥98%, age 96.9%, **realinc 88.6%** - income is the one field with real missingness, so templates omit absent profile fields entirely (never invent a value). Rows missing key demographics (age, sex, region, education) are dropped at build - <4% of the base year.

**`config/gss_questions.yaml`** - calibration questions, verbatim from the GSS codebook (hand-copied - a deliberate manual step):

```yaml
- qid: gss:abany
  var: abany
  text: >
    Please tell me whether or not you think it should be possible for a
    pregnant woman to obtain a legal abortion if the woman wants it for any
    reason?
  qtype: single_choice
  options:
    - {code: 1, text: "Yes"}
    - {code: 2, text: "No"}
```

All 26 questions are present in 2024 (n = 3,309), in coverage tiers set by the split-ballot/rotation design:

| Tier | 2024 valid N | Questions |
|---|---|---|
| Core (~99%) | 3,160–3,294 | happy, health, satfin, polviews, partyid |
| Ballot (~65%) | 2,067–2,191 | abany, cappun, gunlaw, homosex, conlegis, confinan, conarmy, eqwlth, helppoor |
| Spending battery (~49%) | 1,591–1,645 | natenvir, natheal, natrace, natfare, nataid |
| Rotation (~26%) | 812–946 | grass, prayer, fepol, trust, fair, helpful, courts |

Overall targets are solid everywhere; single-dimension subgroup targets on the rotation tier drop to ~200–240 valid per cell - usable but noisy, which is what the `valid_n` floor flag is for.

**Leakage rule:** a variable used in the profile must never appear as a calibration question (and vice versa). `partyid`/`polviews` are kept as *questions*, not profile fields, so political alignment is something the model must infer - exactly what calibration measures. `data build` enforces disjointness and fails if violated.

### Modeling tables

DuckDB tables with Parquet mirrors:

```sql
respondents(
  dataset VARCHAR, resp_id VARCHAR,       -- 'gss:2024:1234'
  year INTEGER, weight DOUBLE, ballot TINYINT,
  yob INTEGER, sex VARCHAR, race VARCHAR, region VARCHAR,
  education VARCHAR, income_bracket VARCHAR, work VARCHAR,
  marital VARCHAR, children TINYINT, religion VARCHAR, attend VARCHAR
)
questions(dataset, qid, var, text, qtype, first_year INT, last_year INT, notes)
options(qid, code SMALLINT, text VARCHAR, ord SMALLINT)
answers_real(dataset, resp_id, year, qid, code SMALLINT)  -- sparse, long
targets(
  qid, year,
  subgroup_dim VARCHAR,     -- 'all' | 'age_bracket' | 'region' | 'education' | 'income'
  subgroup_value VARCHAR,
  code SMALLINT, share DOUBLE,              -- weighted share, sums to 1 per group
  valid_n INTEGER                           -- unweighted N behind the estimate
)
panel(panel_id UUID, agent_id, resp_id, seed, created_at)   -- sampled panel, reused across runs
```

(The run registry and synthetic-answer tables belong to the runner - see [RUNNER.md](RUNNER.md).)

Design notes:

- Every table carries/derives `dataset` and `qid` is dataset-prefixed (`gss:abany`), so ANES/WVS later add rows, not schema.
- `options` is a real table (not JSON) - answer validation and target computation are joins against it; `answers_real` stores codes only, so a wording fix in YAML propagates everywhere on rebuild.
- Subgroup definitions live in config (`config/gss_subgroups.yaml`), and `targets` keeps them as dim/value strings - adding a dimension is config, not schema.

### Commands & validation gates

```
silicon data download   # fetch zip (or --from-file), sha256, land in raw/ + S3; idempotent via manifest
silicon data extract    # read .dta with usecols=configured vars + encoding=latin1, write extracted parquet
silicon data build      # recode -> respondents/questions/options/answers_real in DuckDB; validate; snapshot to S3
silicon data targets    # weighted per-question x subgroup distributions for base_year -> targets
silicon data status     # manifests, row counts, per-question valid_n, thin-cell warnings
```

Validation gates in `build` (all fail loudly, listing offenders):

1. Configured variable absent from the extract (typo'd var or wrong release).
2. Answer code in data with no entry in the question's YAML options.
3. Profile/question variable overlap (leakage rule).
4. Weight variable missing or non-positive weights.
5. A configured question with zero base-year respondents - warning, question excluded for that year.

## Panel & prompts

- `silicon panel sample --n 100 --seed 42` bootstraps whole respondent rows **weighted by `wtssps`** - probability-proportional-to-weight resampling makes the panel self-weighting, so synthetic distributions are plain agent proportions. Panels get a uuid4 `panel_id` and are reused across runs, so template sweeps compare on identical agents.
- `prompts/` holds three system-prompt variants (`v1_neutral`, `v2_persona_rich`, `v3_minimal`) sharing `_contract.j2` (identical JSON answer contract) and `question.j2` (options list; volunteered options toggleable: listed / last-resort / hidden, or `auto` from per-question YAML). Missing profile fields are omitted, never invented.
- `silicon panel render` previews personas + a question for any panel/template.
- `parse_answer` maps replies back to option codes: strips `<think>` blocks, tolerates chatter around the JSON, accepts bare scale numbers, rejects anything not matching an allowed option (the runner's re-ask trigger).

## Scoring & calibration

### Targets

`silicon data targets` computes weighted answer distributions from real respondents: `answers_real ⋈ respondents` filtered to the target year, weighted by `wtssps`, grouped per subgroup dimension. Subgroups come from `config/gss_subgroups.yaml`:

```yaml
- dim: age_bracket
  source: age
  bins: [18, 30, 45, 65, .inf]
  labels: ["18-29", "30-44", "45-64", "65+"]
- dim: region          # categorical columns pass through as-is
  source: region
- dim: education
  source: education
- dim: income
  source: income_bracket
```

One shared helper assigns subgroup columns to any respondent-shaped frame - used identically for real respondents (targets) and panel agents (scoring), so the two sides can never drift. Target cells with `valid_n` below a configured floor (~60) are stored but flagged.

### Metrics

Pure functions in `score/metrics.py`. For each `(qid, subgroup)` cell, target and synthetic shares are aligned over the question's full option list (absent codes → share 0), then:

- **MAE in percentage points**: `mean(|p_target − p_synth|) × 100` over options - the number comparable to the ~8pp results quoted in the LLM-replication literature.
- **Jensen–Shannon distance**: `sqrt(JSD)` with base-2 logs - bounded [0, 1], symmetric, defined even when one side has zero mass on an option.

Run-level rollups are the unweighted mean over questions of the 'all'-subgroup values (every question counts equally).

### Scoring & comparing runs

`silicon score <run_id>` computes synthetic shares from `answers_synth` (`code IS NOT NULL`; plain proportions - the panel is self-weighting by construction), joins against `targets`, and persists a `scores` table plus `reports/<run_id>/scores.parquet`, with rollups into `runs.mae` / `runs.js_distance`. Re-scoring is idempotent (delete-then-insert per run). Low-N cells are flagged, not hidden.

`silicon compare [run_id...]` prints scored runs side by side - template, model, temperature, agents, overall MAE, JS, failures, cost - sorted by MAE. This is the table that answers "which configuration wins" during sweeps. Measured sampling-noise floor at n=10 agents: three identical configs scored 15.4 / 16.7 / 17.9pp.

## API

FastAPI app (`silicon api`, or `docker compose up api` on :8000), backed by the same DuckDB file:

- `POST /questions` - register a prospective question (text + options) → qid `new:<slug>`, runnable by the standard runner.
- `POST /runs` - run prospective questions on the **best calibrated configuration** (panel/template/model/volunteered resolved from the registry's lowest-MAE scored run).
- `GET /runs/{id}` - status + live progress; `GET /runs/{id}/results` - distributions + subgroup crosstabs, each response embedding the calibration caveat (model, template, MAE/JS of the configuration used).
- `GET /calibration` - current best run summary.
