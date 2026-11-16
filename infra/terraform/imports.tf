# Everything here already exists; the import blocks adopt it. CI runs `terraform plan` without state,
# so each run imports again and must show 0 to add, 0 to change, 0 to destroy (docs/terraform.md).

import {
  to = google_artifact_registry_repository.ragdog
  id = "projects/ragdog-511311/locations/asia-northeast3/repositories/ragdog"
}

import {
  to = google_cloud_run_v2_service.api
  id = "projects/ragdog-511311/locations/asia-northeast3/services/ragdog-api"
}

import {
  to = google_service_account.deployer
  id = "projects/ragdog-511311/serviceAccounts/github-deployer@ragdog-511311.iam.gserviceaccount.com"
}

import {
  to = google_service_account.runtime
  id = "projects/ragdog-511311/serviceAccounts/ragdog-runtime@ragdog-511311.iam.gserviceaccount.com"
}

import {
  to = google_service_account.slo_reader
  id = "projects/ragdog-511311/serviceAccounts/slo-reader@ragdog-511311.iam.gserviceaccount.com"
}

import {
  to = google_iam_workload_identity_pool.github
  id = "projects/ragdog-511311/locations/global/workloadIdentityPools/github"
}

import {
  to = google_iam_workload_identity_pool_provider.dograg
  id = "projects/ragdog-511311/locations/global/workloadIdentityPools/github/providers/dograg"
}

import {
  to = google_project_iam_member.deployer_run_viewer
  id = "ragdog-511311 roles/run.viewer serviceAccount:github-deployer@ragdog-511311.iam.gserviceaccount.com"
}

import {
  to = google_project_iam_member.slo_reader_monitoring
  id = "ragdog-511311 roles/monitoring.viewer serviceAccount:slo-reader@ragdog-511311.iam.gserviceaccount.com"
}

import {
  to = google_service_account_iam_member.deployer_wif
  id = "projects/ragdog-511311/serviceAccounts/github-deployer@ragdog-511311.iam.gserviceaccount.com roles/iam.workloadIdentityUser principalSet://iam.googleapis.com/projects/892238791473/locations/global/workloadIdentityPools/github/attribute.repository/rndigkwk/dograg"
}

import {
  to = google_service_account_iam_member.slo_reader_wif
  id = "projects/ragdog-511311/serviceAccounts/slo-reader@ragdog-511311.iam.gserviceaccount.com roles/iam.workloadIdentityUser principalSet://iam.googleapis.com/projects/892238791473/locations/global/workloadIdentityPools/github/attribute.repository/rndigkwk/dograg"
}

import {
  to = google_service_account_iam_member.deployer_acts_as_runtime
  id = "projects/ragdog-511311/serviceAccounts/ragdog-runtime@ragdog-511311.iam.gserviceaccount.com roles/iam.serviceAccountUser serviceAccount:github-deployer@ragdog-511311.iam.gserviceaccount.com"
}

import {
  to = google_artifact_registry_repository_iam_member.deployer_writer
  id = "projects/ragdog-511311/locations/asia-northeast3/repositories/ragdog roles/artifactregistry.writer serviceAccount:github-deployer@ragdog-511311.iam.gserviceaccount.com"
}

import {
  to = google_cloud_run_v2_service_iam_member.deployer_admin
  id = "projects/ragdog-511311/locations/asia-northeast3/services/ragdog-api roles/run.admin serviceAccount:github-deployer@ragdog-511311.iam.gserviceaccount.com"
}

import {
  to = google_cloud_run_v2_service_iam_member.public
  id = "projects/ragdog-511311/locations/asia-northeast3/services/ragdog-api roles/run.invoker allUsers"
}

import {
  to = google_secret_manager_secret.app["ANTHROPIC_API_KEY"]
  id = "projects/ragdog-511311/secrets/ANTHROPIC_API_KEY"
}

import {
  to = google_secret_manager_secret_iam_member.runtime["ANTHROPIC_API_KEY"]
  id = "projects/ragdog-511311/secrets/ANTHROPIC_API_KEY roles/secretmanager.secretAccessor serviceAccount:ragdog-runtime@ragdog-511311.iam.gserviceaccount.com"
}

import {
  to = google_secret_manager_secret.app["ANTHROPIC_WORKSPACE_ID"]
  id = "projects/ragdog-511311/secrets/ANTHROPIC_WORKSPACE_ID"
}

import {
  to = google_secret_manager_secret_iam_member.runtime["ANTHROPIC_WORKSPACE_ID"]
  id = "projects/ragdog-511311/secrets/ANTHROPIC_WORKSPACE_ID roles/secretmanager.secretAccessor serviceAccount:ragdog-runtime@ragdog-511311.iam.gserviceaccount.com"
}

import {
  to = google_secret_manager_secret.app["LANGFUSE_PUBLIC_KEY"]
  id = "projects/ragdog-511311/secrets/LANGFUSE_PUBLIC_KEY"
}

import {
  to = google_secret_manager_secret_iam_member.runtime["LANGFUSE_PUBLIC_KEY"]
  id = "projects/ragdog-511311/secrets/LANGFUSE_PUBLIC_KEY roles/secretmanager.secretAccessor serviceAccount:ragdog-runtime@ragdog-511311.iam.gserviceaccount.com"
}

import {
  to = google_secret_manager_secret.app["LANGFUSE_SECRET_KEY"]
  id = "projects/ragdog-511311/secrets/LANGFUSE_SECRET_KEY"
}

import {
  to = google_secret_manager_secret_iam_member.runtime["LANGFUSE_SECRET_KEY"]
  id = "projects/ragdog-511311/secrets/LANGFUSE_SECRET_KEY roles/secretmanager.secretAccessor serviceAccount:ragdog-runtime@ragdog-511311.iam.gserviceaccount.com"
}

import {
  to = google_secret_manager_secret.app["OPENAI_API_KEY"]
  id = "projects/ragdog-511311/secrets/OPENAI_API_KEY"
}

import {
  to = google_secret_manager_secret_iam_member.runtime["OPENAI_API_KEY"]
  id = "projects/ragdog-511311/secrets/OPENAI_API_KEY roles/secretmanager.secretAccessor serviceAccount:ragdog-runtime@ragdog-511311.iam.gserviceaccount.com"
}

import {
  to = google_secret_manager_secret.app["SUPABASE_DB_URL"]
  id = "projects/ragdog-511311/secrets/SUPABASE_DB_URL"
}

import {
  to = google_secret_manager_secret_iam_member.runtime["SUPABASE_DB_URL"]
  id = "projects/ragdog-511311/secrets/SUPABASE_DB_URL roles/secretmanager.secretAccessor serviceAccount:ragdog-runtime@ragdog-511311.iam.gserviceaccount.com"
}
