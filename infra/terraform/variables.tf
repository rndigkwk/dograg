variable "project" {
  type    = string
  default = "ragdog-511311"
}

variable "project_number" {
  type    = string
  default = "892238791473"
}

variable "region" {
  type    = string
  default = "asia-northeast3"
}

variable "repository" {
  description = "The GitHub repository allowed to log in through Workload Identity."
  type        = string
  default     = "rndigkwk/dograg"
}
