#!/bin/sh
# End-to-end pipe check: connectivity -> panel -> real inference -> scoring -> cleanup.
# ~6 LLM requests. Assumes `silicon data build` and `silicon data targets` have
# populated the database. On failure, throwaway rows are left in place for debugging.
set -e

UUID_RE='[0-9a-f]\{8\}-[0-9a-f]\{4\}-[0-9a-f]\{4\}-[0-9a-f]\{4\}-[0-9a-f]\{12\}'

silicon storage check
silicon llm check

PANEL_OUT=$(silicon panel sample --n 3 --seed 999 --no-upload)
echo "$PANEL_OUT"
PANEL_ID=$(echo "$PANEL_OUT" | grep -o "$UUID_RE" | head -1)
[ -n "$PANEL_ID" ] || { echo "pipe check: could not parse panel id"; exit 1; }

RUN_OUT=$(silicon run start --panel-id "$PANEL_ID" --qids gss:cappun,gss:happy --concurrency 3 --no-upload)
echo "$RUN_OUT"
RUN_ID=$(echo "$RUN_OUT" | grep -o "$UUID_RE" | head -1)
[ -n "$RUN_ID" ] || { echo "pipe check: could not parse run id"; exit 1; }
echo "$RUN_OUT" | grep -q "failed 0" || { echo "pipe check: run had failed tasks"; exit 1; }

silicon score "$RUN_ID" --no-upload | tail -1

silicon run delete "$RUN_ID" --yes
silicon panel delete "$PANEL_ID" --yes
echo "pipe check OK"
