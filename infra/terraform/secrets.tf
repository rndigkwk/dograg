# The app's secrets: only their names and who may read them. The values are added by the owner
# (`gcloud secrets versions add`) and never pass through Terraform or its state.
locals {
  secrets = toset([
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_WORKSPACE_ID",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "OPENAI_API_KEY",
    "SUPABASE_DB_URL",
  ])
}

resource "google_secret_manager_secret" "app" {
  for_each  = local.secrets
  secret_id = each.key
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "runtime" {
  for_each  = local.secrets
  secret_id = google_secret_manager_secret.app[each.key].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}
