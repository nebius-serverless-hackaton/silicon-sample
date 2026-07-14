#!/bin/sh
set -u

silicon storage check
storage_status=$?

silicon llm check
llm_status=$?

if [ "$storage_status" -ne 0 ] || [ "$llm_status" -ne 0 ]; then
  exit 1
fi
