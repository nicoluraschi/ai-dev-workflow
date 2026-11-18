#!/usr/bin/env bash
# Run by lefthook (lefthook.yml) with git's pre-push args and stdin; see scripts/pre-push.
exec scripts/pre-push "$@"
