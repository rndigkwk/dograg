#!/usr/bin/env bash
# Email alerts when the deployed app logs an outage (docs/wiki/observability.md). Run it once in
# Cloud Shell as the project owner, from the repository root:
#
#   ALERT_EMAIL=you@example.com bash scripts/gcp/setup_alerts.sh
#
# Creates an email notification channel and one log-match alert policy per entry of
# scripts/gcp/alert_policies.json: an email when a matching line is logged, at most one per policy
# per hour, closed after 30 minutes without another. Safe to run again: an existing channel for the
# address and existing policies (by display name) are kept.
set -euo pipefail

PROJECT_ID="ragdog-511311"
POLICIES="$(dirname "$0")/alert_policies.json"
: "${ALERT_EMAIL:?set ALERT_EMAIL to the address that should get the alerts}"

gcloud config set project "$PROJECT_ID" >/dev/null
gcloud services enable monitoring.googleapis.com logging.googleapis.com

channel="$(gcloud beta monitoring channels list \
  --filter="type=\"email\" AND labels.email_address=\"$ALERT_EMAIL\"" --format='value(name)' | head -n1)"
if [ -z "$channel" ]; then
  channel="$(gcloud beta monitoring channels create --display-name="RagDog alerts" --type=email \
    --channel-labels=email_address="$ALERT_EMAIL" --format='value(name)')"
  echo "created the email channel (Google sends no confirmation mail for email channels)"
fi

count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["policies"]))' "$POLICIES")"
for index in $(seq 0 $((count - 1))); do
  file="$(mktemp)"
  name="$(python3 - "$POLICIES" "$index" "$channel" "$file" <<'PY'
import json, sys
policies, index, channel, out = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
entry = json.load(open(policies, encoding="utf-8"))["policies"][index]
json.dump({
    "displayName": entry["displayName"],
    "documentation": {"content": entry["documentation"], "mimeType": "text/markdown"},
    "combiner": "OR",
    "conditions": [{"displayName": entry["displayName"], "conditionMatchedLog": {"filter": entry["filter"]}}],
    "alertStrategy": {"notificationRateLimit": {"period": "3600s"}, "autoClose": "1800s"},
    "notificationChannels": [channel],
}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
print(entry["displayName"])
PY
)"
  if [ -n "$(gcloud alpha monitoring policies list --filter="displayName=\"$name\"" --format='value(name)')" ]; then
    echo "kept: $name"
  else
    gcloud alpha monitoring policies create --policy-from-file="$file" >/dev/null
    echo "created: $name"
  fi
  rm -f "$file"
done
