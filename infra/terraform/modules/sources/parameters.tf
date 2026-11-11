# Connection details for the simulator and the pipelines (standard tier, free). Secret values
# also sit in Terraform state, which lives in the private, encrypted state bucket.

locals {
  plain_parameters = {
    "aws/region"               = local.region
    "postgres/host"            = data.aws_db_instance.shared.address
    "postgres/port"            = tostring(data.aws_db_instance.shared.port)
    "postgres/database"        = postgresql_database.casedesk.name
    "postgres/schema"          = postgresql_schema.casedesk.name
    "postgres/username"        = postgresql_role.owner.name
    "postgres/reader_username" = postgresql_role.reader.name
    "activity_api/url"         = "${aws_api_gateway_stage.v1.invoke_url}/activities"
    "s3/sources_bucket"        = aws_s3_bucket.this["sources"].bucket
    "s3/simulator_bucket"      = aws_s3_bucket.this["simulator"].bucket
    "dynamodb/segments_table"  = aws_dynamodb_table.segments.name
    "sftp/username"            = local.sftp_user
    "sftp/port"                = "22"
    "sftp/host_parameter"      = var.shared_sftp_host_parameter
    "rds/instance_identifier"  = data.aws_db_instance.shared.db_instance_identifier
    "sftp/instance_id"         = data.aws_instance.shared_sftp.id
  }
  secret_parameters = {
    "postgres/password"        = random_password.owner.result
    "postgres/reader_password" = random_password.reader.result
    "sftp/private_key"         = tls_private_key.sftp.private_key_openssh
    "activity_api/api_key"     = aws_api_gateway_api_key.activity.value
  }
}

resource "aws_ssm_parameter" "plain" {
  for_each = local.plain_parameters
  name     = "${var.parameter_prefix}/${each.key}"
  type     = "String"
  value    = each.value
}

resource "aws_ssm_parameter" "secret" {
  for_each = local.secret_parameters
  name     = "${var.parameter_prefix}/${each.key}"
  type     = "SecureString"
  value    = each.value
}
