# The API service. Each deploy (.github/workflows/deploy-cloud-run.yml) sets the image, the
# environment (LANGFUSE_RELEASE is the commit), the revision and the traffic split with its
# candidate tag, so those are left to the workflow; everything else here is checked for drift.
resource "google_cloud_run_v2_service" "api" {
  name                = "ragdog-api"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = true

  scaling {
    min_instance_count = 0
  }

  template {
    service_account                  = google_service_account.runtime.email
    max_instance_request_concurrency = 80
    timeout                          = "900s"

    scaling {
      min_instance_count = 0 # scale to zero: no questions, no bill (ADR-0013)
      max_instance_count = 2
    }

    containers {
      image   = "${var.region}-docker.pkg.dev/${var.project}/${google_artifact_registry_repository.ragdog.repository_id}/app:latest"
      command = ["uvicorn"]
      args    = ["api.main:app", "--host", "0.0.0.0", "--port", "8080"]

      ports {
        name           = "http1"
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "2Gi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      startup_probe {
        failure_threshold = 1
        period_seconds    = 240
        timeout_seconds   = 240
        tcp_socket {
          port = 8080
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  lifecycle {
    ignore_changes = [
      client,
      client_version,
      template[0].revision,
      template[0].containers[0].image,
      template[0].containers[0].env,
      traffic,
    ]
  }
}

# The browser calls the API directly (ADR-0008); the deployer replaces revisions.
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.api.id
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "deployer_admin" {
  name     = google_cloud_run_v2_service.api.id
  location = var.region
  role     = "roles/run.admin"
  member   = "serviceAccount:${google_service_account.deployer.email}"
}
