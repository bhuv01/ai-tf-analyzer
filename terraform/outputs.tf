output "lambda_function_name" { value = aws_lambda_function.analyzer.function_name }
output "lambda_function_arn"  { value = aws_lambda_function.analyzer.arn }
output "sns_topic_arn"        { value = aws_sns_topic.alerts.arn }
output "log_group_name"       { value = aws_cloudwatch_log_group.lambda.name }

output "next_steps" {
  value = <<-EOT

    ✅ Deployment complete! Next steps:

    1. Check your email (${var.alert_email}) — confirm SNS subscription
    2. Copy this for Jenkins environment block:
         LAMBDA_FUNCTION_NAME = "${aws_lambda_function.analyzer.function_name}"
         AWS_REGION           = "${var.aws_region}"
    3. Test it:
         ./scripts/analyze.sh --sample
  EOT
}
