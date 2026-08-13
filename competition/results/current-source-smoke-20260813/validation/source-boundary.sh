#!/usr/bin/env bash

set -euo pipefail

upstream=56f8bfc8207f38d4b395dae0cf533ecdb079fca8
rt_source=077ba386c20c29b84749f509b29e8a3f6f76e1e2
ivc_source=598b357f92c848e669c12cca830a4d08d0a50e36
bundle=${BUNDLE:?set BUNDLE to the evidence bundle path}

printf 'source_validation_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'head=%s\n' "$(git rev-parse HEAD)"
printf 'tree=%s\n' "$(git rev-parse 'HEAD^{tree}')"
printf 'upstream_dev=%s\n' "$upstream"
git merge-base --is-ancestor "$upstream" HEAD
printf 'upstream_ancestor=PASS\n'
read -r behind ahead < <(git rev-list --left-right --count "$upstream...HEAD")
printf 'ahead=%s\nbehind=%s\n' "$ahead" "$behind"
test -z "$(git status --porcelain=v1)"
printf 'clean_worktree=PASS\n'
printf 'rt_commit=%s\n' "$rt_source"
printf 'rt_tree=%s\n' "$(git rev-parse "$rt_source^{tree}")"
printf 'ivc_commit=%s\n' "$ivc_source"
printf 'delta_begin\n'
git diff --name-status "$rt_source..$ivc_source"
printf 'delta_end\n'
test -z "$(
    git diff --name-only "$rt_source..$ivc_source" -- . ':!competition/ivc'
)"
printf 'rt_runtime_config_unchanged=PASS\n'
sha256sum -c "$bundle/runtime-inputs.sha256"
