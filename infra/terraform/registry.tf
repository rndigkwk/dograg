# Images hold AI Hub-derived data (Dockerfile): the repository stays private.
resource "google_artifact_registry_repository" "ragdog" {
  repository_id = "ragdog"
  location      = var.region
  format        = "DOCKER"
  description   = "RagDog app images (contain AI Hub-derived data: keep private)"

  # Keep the three newest images (rollback targets), delete the rest after a day.
  cleanup_policies {
    id     = "delete-older"
    action = "DELETE"
    condition {
      tag_state  = "ANY"
      older_than = "86400s"
    }
  }
  cleanup_policies {
    id     = "keep-3-newest"
    action = "KEEP"
    most_recent_versions {
      keep_count = 3
    }
  }
}

resource "google_artifact_registry_repository_iam_member" "deployer_writer" {
  repository = google_artifact_registry_repository.ragdog.id
  location   = var.region
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deployer.email}"
}
