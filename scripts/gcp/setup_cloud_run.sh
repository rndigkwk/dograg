#!/usr/bin/env bash
# One-time Google Cloud setup for deploying RagDog to Cloud Run from GitHub Actions
# (.github/workflows/deploy-cloud-run.yml). Run it in Cloud Shell as the project owner:
#
#   bash setup_cloud_run.sh
#
# Creates: a private Artifact Registry repository, a runtime and a deployer service account,
# a Workload Identity pool/provider that only this GitHub repository can use (no key files),
# and Secret Manager secrets (values are typed in hidden, never echoed or stored in the script).
# Safe to run again: existing resources are kept.
set -euo pipefail

PROJECT_ID="ragdog-511311"
REGION="asia-northeast3"           # Seoul
GITHUB_REPO="rndigkwk/dograg"
AR_REPO="ragdog"
RUNTIME_SA="ragdog-runtime"
DEPLOYER_SA="github-deployer"
POOL="github"
PROVIDER="dograg"
SECRETS=(OPENAI_API_KEY LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY SUPABASE_DB_URL)

gcloud config set project "$PROJECT_ID" >/dev/null
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUNTIME="$RUNTIME_SA@$PROJECT_ID.iam.gserviceaccount.com"
DEPLOYER="$DEPLOYER_SA@$PROJECT_ID.iam.gserviceaccount.com"

echo "== APIs"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com

echo "== Artifact Registry (private)"
gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" >/dev/null 2>&1 ||
  gcloud artifacts repositories create "$AR_REPO" --repository-format=docker --location="$REGION" \
    --description="RagDog app images (contain AI Hub-derived data: keep private)"

# Each image is ~2.75 GB (layers are shared, but versions pile up): keep the 3 newest, delete the rest.
cat > /tmp/ragdog-cleanup.json <<'POLICY'
[
  {"name": "keep-3-newest", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 3}},
  {"name": "delete-older", "action": {"type": "Delete"}, "condition": {"tagState": "ANY", "olderThan": "1d"}}
]
POLICY
gcloud artifacts repositories set-cleanup-policies "$AR_REPO" --location="$REGION" \
  --policy=/tmp/ragdog-cleanup.json --no-dry-run >/dev/null

echo "== Service accounts"
for sa in "$RUNTIME_SA" "$DEPLOYER_SA"; do
  gcloud iam service-accounts describe "$sa@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1 ||
    gcloud iam service-accounts create "$sa" --display-name="RagDog $sa"
done
# The deployer pushes images and deploys the service as the runtime account; it holds no data access.
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$DEPLOYER" \
  --role=roles/run.admin --condition=None >/dev/null
gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" --location="$REGION" \
  --member="serviceAccount:$DEPLOYER" --role=roles/artifactregistry.writer >/dev/null
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME" --member="serviceAccount:$DEPLOYER" \
  --role=roles/iam.serviceAccountUser >/dev/null

echo "== Workload Identity Federation (GitHub Actions of $GITHUB_REPO only)"
gcloud iam workload-identity-pools describe "$POOL" --location=global >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools create "$POOL" --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers describe "$PROVIDER" --location=global \
  --workload-identity-pool="$POOL" >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" --location=global \
    --workload-identity-pool="$POOL" --display-name="$GITHUB_REPO" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository == '$GITHUB_REPO'"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER" --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/attribute.repository/$GITHUB_REPO" \
  >/dev/null

echo "== Secrets (typed in hidden; press Enter on an empty value to skip one)"
for name in "${SECRETS[@]}"; do
  if gcloud secrets describe "$name" >/dev/null 2>&1; then
    echo "$name: already exists (add a new version in the console to change it)"
  else
    read -rsp "$name: " value; echo
    if [ -n "$value" ]; then
      printf '%s' "$value" | gcloud secrets create "$name" --replication-policy=automatic --data-file=- >/dev/null
      echo "$name: created"
    else
      echo "$name: skipped"
      continue
    fi
    unset value
  fi
  gcloud secrets add-iam-policy-binding "$name" --member="serviceAccount:$RUNTIME" \
    --role=roles/secretmanager.secretAccessor >/dev/null
done

echo
echo "Done. Values for the workflow (identifiers, not secrets):"
echo "  WORKLOAD_IDENTITY_PROVIDER=projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/providers/$PROVIDER"
echo "  DEPLOYER=$DEPLOYER"
echo "  RUNTIME=$RUNTIME"
