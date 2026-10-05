#!/usr/bin/env bash
# Calls a command that is on no image, then carries on and writes an output.
# Without the SDK's command_not_found_handle this run would come back `ok`;
# the smoke test expects it to fail with E_COMMAND_NOT_FOUND.
source "$RW_SDK/rw.sh"

result=$(rw-smoke-no-such-tool 2>/dev/null || true)
rw_set message "{\"text\": \"carried on${result}\"}"
