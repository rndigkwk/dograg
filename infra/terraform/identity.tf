# Keyless GitHub Actions login (Workload Identity): only this repository's main branch.
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
}

resource "google_iam_workload_identity_pool_provider" "dograg" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "dograg"
  display_name                       = var.repository
  attribute_condition                = "assertion.repository == '${var.repository}' && assertion.ref == 'refs/heads/main'"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

locals {
  github_actions = "principalSet://iam.googleapis.com/projects/${var.project_number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github.workload_identity_pool_id}/attribute.repository/${var.repository}"
}

# Deploys and rolls back the API (deploy-cloud-run.yml, rollback-api.yml).
resource "google_service_account" "deployer" {
  account_id   = "github-deployer"
  display_name = "RagDog github-deployer"
}

# What the API runs as: reads its secrets, nothing else.
resource "google_service_account" "runtime" {
  account_id   = "ragdog-runtime"
  display_name = "RagDog ragdog-runtime"
}

# Reads Cloud Run's request counts for the weekly SLO report (slo-weekly.yml).
resource "google_service_account" "slo_reader" {
  account_id   = "slo-reader"
  display_name = "Weekly SLO report (read-only)"
}

resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.github_actions
}

resource "google_service_account_iam_member" "slo_reader_wif" {
  service_account_id = google_service_account.slo_reader.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.github_actions
}

# The deployer may start revisions that run as the runtime account.
resource "google_service_account_iam_member" "deployer_acts_as_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_member" "deployer_run_viewer" {
  project = var.project
  role    = "roles/run.viewer"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_member" "slo_reader_monitoring" {
  project = var.project
  role    = "roles/monitoring.viewer"
  member  = "serviceAccount:${google_service_account.slo_reader.email}"
}
