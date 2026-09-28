#!/usr/bin/env bash
# Echo the `greeting` input back as the `message` output. Inputs arrive as
# upper-cased env vars; outputs are written with the SDK's bash helpers,
# rw_set() and rw_append().
set -euo pipefail

source "$RW_SDK/rw.sh"

rw_set message "{\"text\": \"${GREETING}\"}"
