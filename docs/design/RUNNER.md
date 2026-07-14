# Inference runner

*Internal design doc: the async batch engine behind `silicon run`. For the surrounding system see [ARCHITECTURE.md](ARCHITECTURE.md).*

## Shape

Package `src/silicon/run/`:

```
run/
  registry.py   # runs table: create / update / get / list
  runner.py     # async batch engine
```

plus an `AsyncOpenAI` factory in `core/llm.py` and a `run` CLI subapp.

## Work model

A **task** is one `(agent_id, qid)` pair; a run is the cross product of a panel's agents × a question set (default: all 26 config questions). Per agent, the system prompt is rendered once and reused for all its questions. Each task sends `[system: persona, user: question]` - one-shot, no conversation history between questions (each question answered independently, like the split-ballot interview it replays).

Defaults (all CLI-overridable): `temperature=1.0` (survey replication samples a distribution - greedy decoding would collapse every identical persona to one answer), `max_tokens=1024` (reasoning models think out loud), model = `NEBIUS_TOKENFACTORY_MODEL_DEV`, `concurrency=16`.

## Tables

```sql
runs(
  run_id UUID PRIMARY KEY,         -- uuid4, native DuckDB UUID type
  created_at, status,              -- running | complete | interrupted | failed
  panel_id UUID,                   -- → panel
  template_id, model, temperature, question_set,
  n_agents, n_questions, n_answered, n_failed,
  prompt_tokens, completion_tokens, cost_usd,   -- cost null if model unpriced
  mae, js_distance,                -- rollups written by scoring
  config JSON                      -- full CLI/config snapshot for reproducibility
)
answers_synth(
  run_id UUID,                     -- → runs
  agent_id, qid,
  code SMALLINT,                   -- NULL = failed after all re-asks
  raw_response VARCHAR, error VARCHAR, retries TINYINT,
  prompt_tokens INT, completion_tokens INT, latency_ms INT, created_at
)
```

Scoring reads `code IS NOT NULL`; failures stay queryable with their raw replies. On completion: `runs/<run_id>/answers.parquet` + `config.json` to S3.

## Error handling - two distinct loops

1. **Transport loop** (network, 429, 5xx, timeouts): exponential backoff with jitter, ~5 attempts, honours `Retry-After` on 429.
2. **Contract loop** (reply doesn't survive `parse_answer`): up to 2 re-asks. A re-ask appends the model's bad reply + a corrective user message ("Reply with only JSON {\"answer\": ...}, exactly one of the offered options") - converges faster than blind resampling. After 2 failures the task records a NULL-code row with the error and the run moves on.

## Concurrency & persistence

- `asyncio` + `AsyncOpenAI`, semaphore-bounded (flag, default 16).
- Results flow through an in-process queue to a single writer that batch-inserts into DuckDB every 50 results (DuckDB is single-writer; a crash loses at most one batch).
- **Resume**: task planning queries existing `(agent_id, qid)` pairs for the run_id and skips them - `silicon run resume <run_id>` after a crash or Ctrl-C only fills gaps. SIGINT flushes the queue, marks `interrupted`, prints the resume command.
- Progress: rich progress bar (answered / failed / tokens).

## Cost accounting

Token usage summed from API responses. `config/models.yaml` maps model id → $/Mtok in/out (optional - unknown models track tokens, cost stays NULL).

## CLI

```
silicon run start  --panel-id <uuid> --template v1_neutral
                   [--model ID] [--qids gss:cappun,...] [--agents N]
                   [--concurrency 16] [--temperature 1.0] [--no-upload]
silicon run resume <run_id>
silicon run list | show <run_id>
```

`--agents N` truncates to the first N agents - the cheap smoke-run knob.
