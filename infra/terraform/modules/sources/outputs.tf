output "sources_bucket" {
  value = aws_s3_bucket.this["sources"].bucket
}

output "simulator_bucket" {
  value = aws_s3_bucket.this["simulator"].bucket
}

output "postgres" {
  value = "${data.aws_db_instance.shared.endpoint}/${postgresql_database.casedesk.name} (schema ${postgresql_schema.casedesk.name})"
}

output "activity_api_url" {
  value = "${aws_api_gateway_stage.v1.invoke_url}/activities"
}

output "segments_table" {
  value = aws_dynamodb_table.segments.name
}

output "sftp_user" {
  value = "${local.sftp_user} on ${data.aws_instance.shared_sftp.id}"
}

output "parameter_prefix" {
  description = "Every connection detail, including secrets, is under this Parameter Store path"
  value       = var.parameter_prefix
}

output "iam_users" {
  value = {
    simulator = aws_iam_user.simulator.name
    pipelines = aws_iam_user.pipelines.name
  }
}
