#!/usr/bin/env bash
# Assemble the submission zip from a run:  scripts/make_submission.sh <run-dir> <traces-dir> [out.zip]
# Contents: README, design card (pdf + md), action_log.jsonl, models.json, one trace per event, grader report,
# ontology export, demo media, and a source snapshot of the current commit.
set -euo pipefail
cd "$(dirname "$0")/.."
run="${1:-runs/live}"; traces="${2:-traces/live}"; out="${3:-wacky-wheels-control-tower.zip}"
stage=$(mktemp -d)/wacky-wheels-control-tower
mkdir -p "$stage/traces" "$stage/source" "$stage/demo"
[ -f "$run/action_log.jsonl" ] || { echo "missing $run/action_log.jsonl" >&2; exit 1; }
n=$(ls "$traces"/E-*.json 2>/dev/null | wc -l | tr -d ' ')
[ "$n" = "15" ] || { echo "expected 15 event traces in $traces, found $n" >&2; exit 1; }
cp README.md docs/design_card.pdf docs/design_card.md docs/ontology.mmd docs/ontology.png "$stage/"
cp "$run/action_log.jsonl" "$stage/"; [ -f "$run/models.json" ] && cp "$run/models.json" "$stage/"
cp "$traces"/E-*.json "$stage/traces/"
uv run python eval/replay_grader.py "$run/action_log.jsonl" --traces "$traces" > "$stage/grader_report.md" 2>&1 || true
[ -d media ] && cp -R media/. "$stage/demo/" || true
git archive --format=tar HEAD | tar -x -C "$stage/source"
printf 'Source commit: %s\nRepository: %s\n' "$(git rev-parse HEAD)" "$(git remote get-url origin)" > "$stage/SOURCE.txt"
rm -f "$out"; (cd "$(dirname "$stage")" && zip -qr "$OLDPWD/$out" "$(basename "$stage")")
echo "wrote $out ($(du -h "$out" | cut -f1)); grader: $(tail -1 "$stage/grader_report.md")"
