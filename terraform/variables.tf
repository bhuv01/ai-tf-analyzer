variable "aws_region" {
  type = string
}

variable "bedrock_region" {
  type = string
}

variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "alert_email" {
  type        = string
  description = "Email for HIGH risk alerts (Gmail works)"
}

variable "bedrock_model_id" {
  type = string
}

variable "lambda_timeout" {
  type    = number
  default = 120
}

variable "lambda_memory" {
  type    = number
  default = 256
}

variable "log_retention_days" {
  type    = number
  default = 7
}

variable "max_tokens" {
  type    = number
  default = 2048
}
