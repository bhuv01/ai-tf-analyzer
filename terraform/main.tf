# ═══════════════════════════════════════════════════════════════════════════════
# main.tf — AI-Powered Terraform Plan Analyzer
# Free tier friendly: Lambda + SNS Email + CloudWatch
# ═══════════════════════════════════════════════════════════════════════════════

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      Purpose     = "ai-tf-plan-analyzer"
    }
  }
}

locals {
  fn_name = "${var.project_name}-${var.environment}-analyzer"
}

# ── Lambda ZIP ────────────────────────────────────────────────────────────────
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.module}/.build/lambda.zip"
}

# ── SNS Topic for Email/Gmail Alerts (FREE) ───────────────────────────────────
resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-${var.environment}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ── IAM Role ──────────────────────────────────────────────────────────────────
resource "aws_iam_role" "lambda" {
  name = "${local.fn_name}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# ── IAM Policies (Least Privilege) ────────────────────────────────────────────
resource "aws_iam_policy" "logging" {
  name = "${local.fn_name}-logging"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ]
      Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${local.fn_name}:*"
    }]
  })
}

resource "aws_iam_policy" "bedrock" {
  name = "${local.fn_name}-bedrock"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["bedrock:InvokeModel"]
      Resource = [
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-5-sonnet-20240620-v1:0",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
        "arn:aws:bedrock:*:*:inference-profile/*"
      ]
    }]
  })
}

resource "aws_iam_policy" "sns" {
  name = "${local.fn_name}-sns"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sns:Publish"]
      Resource = aws_sns_topic.alerts.arn
    }]
  })
}

resource "aws_iam_role_policy_attachment" "logging" {
  role       = aws_iam_role.lambda.name
  policy_arn = aws_iam_policy.logging.arn
}

resource "aws_iam_role_policy_attachment" "bedrock" {
  role       = aws_iam_role.lambda.name
  policy_arn = aws_iam_policy.bedrock.arn
}

resource "aws_iam_role_policy_attachment" "sns" {
  role       = aws_iam_role.lambda.name
  policy_arn = aws_iam_policy.sns.arn
}

# ── CloudWatch Log Group ──────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.fn_name}"
  retention_in_days = var.log_retention_days
}

# ── Lambda Function ───────────────────────────────────────────────────────────
resource "aws_lambda_function" "analyzer" {
  function_name    = local.fn_name
  description      = "AI-powered Terraform plan analyzer using Bedrock Claude"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda.arn
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory

  environment {
    variables = {
      BEDROCK_REGION   = var.bedrock_region
      BEDROCK_MODEL_ID = var.bedrock_model_id
      MAX_TOKENS       = tostring(var.max_tokens)
      SNS_TOPIC_ARN    = aws_sns_topic.alerts.arn
      ENVIRONMENT      = var.environment
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.logging,
    aws_iam_role_policy_attachment.bedrock,
    aws_iam_role_policy_attachment.sns,
    aws_cloudwatch_log_group.lambda,
  ]
}
