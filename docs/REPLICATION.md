# Replication guide

Every command below runs inside Docker - no local Python required. Following the whole guide reproduces the full evidence base behind [CONCLUSIONS.md](CONCLUSIONS.md) and the README figures: roughly **101,000 LLM requests / ~30M tokens** across 43 registry runs, plus throwaway smoke runs (a few dollars on a 70B-class model at current Nebius prices; the historical sweep in step 7 is ~75% of it). Steps 1–5 alone give a working pipeline for ~6 requests.

Because runs sample at temperature 1.0 and a 100-agent panel carries noise of its own, expect your numbers to match ours within **±1–2pp**, not exactly. Orderings and bands should reproduce; single decimals won't. (This guide has been executed end-to-end twice; the leader configuration scored 12.9pp and 11.6pp on the two passes.)

## 1. Prerequisites

- Docker with Compose
- A [Nebius AI Studio](https://studio.nebius.ai/) API key
- `git clone <this repo> && cd silicon-sample`

## 2. Configure

```sh
cp .env.example .env
```

Edit `.env`:

- `NEBIUS_TOKENFACTORY_API_KEY` - your key. Required.
- `NEBIUS_TOKENFACTORY_MODEL_DEV="NousResearch/Hermes-4-70B"` - the full model id, exactly. All calibration runs use this model by default, and the figure script filters on the exact string.
- The `NEBIUS_S3_*` block is **optional**. This guide passes `--no-upload` everywhere so nothing needs object storage; if you do configure a bucket, drop the `--no-upload` flags to get durable parquet copies of every artifact.
- Optional: put current per-million-token prices into `config/models.yaml` to have `cost_usd` tracked per run (missing prices just leave it null).

## 3. Get the GSS data

The raw file is a direct public download from NORC (no registration; zip ~47MB, unpacks to ~570MB):

```sh
mkdir -p data
curl -L -o data/GSS_stata.zip "https://gss.norc.org/content/dam/gss/get-the-data/documents/stata/GSS_stata.zip"
unzip -j data/GSS_stata.zip -d data/GSS_stata   # -j flattens; the zip sometimes nests a GSS_stata/ folder
ls data/GSS_stata/gss7224_r3a.dta   # must exist
```

The config pins Release 3a (`gss7224_r3a.dta`, July 2026). If NORC has since published a newer release, the filename inside the zip changes - update `dta_path` (and `release`) in `config/gss_dataset.yaml` and expect small shifts in the numbers. (For the R3 → R3a update this guide was verified against, every pipeline row count came out identical.)

## 4. Build the image and smoke-check

```sh
docker compose build
docker compose run --rm test                      # 127 tests, no network needed
docker compose run --rm app silicon llm check     # one real completion against the dev model
```

(With S3 configured you can use `docker compose run --rm sanity`, which also round-trips the bucket.)

## 5. Data pipeline and end-to-end smoke run

No LLM calls; a few minutes of CPU for the 570MB `.dta`:

```sh
docker compose run --rm app silicon data extract --no-upload
docker compose run --rm app silicon data build --no-upload
docker compose run --rm app silicon data targets --no-upload
```

Expected: `build` reports **74,627 respondents** and **1,269,397 answers_real** rows; `targets` reports **41,462 rows: 35 rounds, 26 questions**.

Then a throwaway end-to-end run (~6 LLM requests) - copy the panel/run UUIDs from each command's output:

```sh
docker compose run --rm app silicon panel sample --n 3 --seed 999 --no-upload
docker compose run --rm app silicon run start --panel-id <PANEL_ID> --qids gss:cappun,gss:happy --concurrency 3 --no-upload
docker compose run --rm app silicon score <RUN_ID> --no-upload
docker compose run --rm app silicon run delete <RUN_ID> --yes
docker compose run --rm app silicon panel delete <PANEL_ID> --yes
```

(With S3 configured, `docker compose run --rm pipe` does all of this in one shot.)

## 6. Calibration experiments on the 2024 panel

One panel, reused by every run so configurations compare on identical agents:

```sh
docker compose run --rm app silicon panel sample --n 100 --seed 42 --no-upload
```

Save the printed `PANEL_ID`. Each run below is 100 agents × 26 questions = **2,600 requests, ~0.8M tokens, a few minutes at concurrency 16**. Score each run right after it finishes.

**Prompt-tuning ladder (figure 3)** - three template styles with volunteered options listed, then the calibrated presentation:

```sh
docker compose run --rm app silicon run start --panel-id <PANEL_ID> --template v3_minimal      --volunteered listed --no-upload
docker compose run --rm app silicon run start --panel-id <PANEL_ID> --template v2_persona_rich --volunteered listed --no-upload
docker compose run --rm app silicon run start --panel-id <PANEL_ID> --template v1_neutral      --volunteered listed --no-upload
docker compose run --rm app silicon run start --panel-id <PANEL_ID> --template v1_neutral      --volunteered auto   --no-upload
docker compose run --rm app silicon score <RUN_ID> --no-upload    # once per run
```

The last one is the **leader configuration**; expect MAE somewhere around 11.5–13pp (our two full passes: 12.9 and 11.6). It also feeds figures 2 and 4.

**Model bake-off (figure 5)** - same panel and template, leader presentation, four more models:

```sh
docker compose run --rm app silicon run start --panel-id <PANEL_ID> --template v1_neutral --volunteered auto --no-upload --model NousResearch/Hermes-4-405B
docker compose run --rm app silicon run start --panel-id <PANEL_ID> --template v1_neutral --volunteered auto --no-upload --model openai/gpt-oss-120b
docker compose run --rm app silicon run start --panel-id <PANEL_ID> --template v1_neutral --volunteered auto --no-upload --model meta-llama/Llama-3.3-70B-Instruct
docker compose run --rm app silicon run start --panel-id <PANEL_ID> --template v1_neutral --volunteered auto --no-upload --model Qwen/Qwen3-235B-A22B-Instruct-2507
```

Check the leaderboard at any point:

```sh
docker compose run --rm app silicon compare
```

If a run crashes mid-flight, `silicon run resume <RUN_ID>` fills only the missing (agent, question) pairs.

## 7. Historical sweep, 1972–2022 (figure 1)

The big one: **34 rounds ≈ 79,600 requests** (per-round question count varies with the split-ballot design), several hours at concurrency 16. The script skips already-completed rounds, so it is safe to interrupt and relaunch.

Two operational notes. The sweep holds the DuckDB write lock for its whole duration - if you plan to run step 8, do it first (the two are independent), and don't use other `silicon` commands or the API until the sweep finishes. And ignore any `RuntimeError: Event loop is closed` httpx-cleanup tracebacks between rounds - they're cosmetic; a round succeeded as long as its `<year>: … MAE …` line printed.

Without S3, first flip the hardcoded upload flag: in `scripts/waves_sweep.py`, change `upload=True` to `upload=False` in the `plan_start(...)` call. Then:

```sh
docker compose run --rm app python scripts/waves_sweep.py
```

Each round prints its own MAE as it completes; expect a roughly 12–18pp band, with the thinnest early round (1972, 9 questions) sometimes poking above it.

## 8. Fresh-poll anchor questions (figure 0)

Start the API and register the five prospective questions exactly as we asked them:

```sh
docker compose up -d api

curl -s -X POST localhost:8000/questions -H 'Content-Type: application/json' -d '{"slug": "phone-ban-class", "text": "Do you support or oppose banning middle school and high school students from using cellphones during class?", "options": ["Support", "Oppose", "Not sure"]}'
curl -s -X POST localhost:8000/questions -H 'Content-Type: application/json' -d '{"slug": "phone-ban-all-day", "text": "Do you support or oppose banning middle school and high school students from using cellphones during the entire school day, including at lunch and between classes?", "options": ["Support", "Oppose", "Not sure"]}'
curl -s -X POST localhost:8000/questions -H 'Content-Type: application/json' -d '{"slug": "ai-jobs-20yr", "text": "Over the next 20 years, do you think the use of artificial intelligence (AI) will lead to more jobs, fewer jobs, or will not make much difference in the number of jobs in the United States?", "options": ["More jobs", "Fewer jobs", "Will not make much difference", "Not sure"]}'
curl -s -X POST localhost:8000/questions -H 'Content-Type: application/json' -d '{"slug": "glp1-medicare", "text": "Prescription drugs such as Ozempic and Wegovy are increasingly used for weight loss. Do you think Medicare should cover the cost of these drugs when prescribed for weight loss for people who are overweight?", "options": ["Yes, Medicare should cover them", "No, Medicare should not cover them"]}'
curl -s -X POST localhost:8000/questions -H 'Content-Type: application/json' -d '{"slug": "housing-density", "text": "Would you favor or oppose changing zoning rules to allow more apartment buildings to be built in neighborhoods that currently allow only single-family homes?", "options": ["Favor", "Oppose", "Not sure"]}'
```

Run them on the 2024 panel with the leader configuration (as the original anchor run did - `gss:partyid` rides along as an in-sample sanity item):

```sh
docker compose run --rm app silicon run start --panel-id <PANEL_ID> --volunteered auto --no-upload \
  --qids new:ai-jobs-20yr,new:phone-ban-class,new:phone-ban-all-day,new:glp1-medicare,new:housing-density,gss:partyid
```

Reference points from our two passes: class phone ban 73–74% support (Pew: 74), all-day ban 47–51% (Pew: 44), AI fewer jobs 63–74% (Pew: 64), Medicare/GLP-1 88% yes both times (KFF: 61 - the documented miss, stable across replications).

Alternatively, `POST /runs {"qids": [...]}` runs prospective questions on the best-scored calibration automatically, and `GET /runs/<id>/results` returns distributions with subgroup crosstabs. `docker compose down` when finished.

## 9. Regenerate the figures

`scripts/make_figures.py` pins the run UUIDs **of our registry** in its constants - yours will differ. Edit the block at the top of the script:

- `LEADER_2024` - your `v1_neutral` + `auto` run id (best MAE in `silicon compare`)
- `CONFIGS` - the four step-6 prompt-ladder run ids
- `MODELS` - the five bake-off run ids
- `ANCHOR_RUN` - the step-8 run id

Then:

```sh
docker compose run --rm app uv run --with matplotlib python scripts/make_figures.py
```

PNGs land in `docs/figures/`. Figure 1 selects sweep runs by query (no editing needed), but only matches `model = 'NousResearch/Hermes-4-70B'` - another reason to set the dev model id exactly in step 2. The pipeline diagram (`fig_pipeline`) is drawn from constants and needs no runs at all.

## Known sources of drift

- **Sampling noise**: temperature 1.0 and 100 agents give ±1–2pp between identical runs (measured at n=10 agents: 15.4 / 16.7 / 17.9pp for three identical configs). Don't over-read small gaps.
- **Model drift**: Nebius may update hosted model builds; the model *id* pins less than a checksum would.
- **GSS releases**: a newer NORC release changes the `.dta` filename and can revise historical weights slightly.
