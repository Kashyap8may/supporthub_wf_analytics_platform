# Two machine users for Databricks Free Edition, which cannot assume an IAM role in this account.
# Terraform creates no access keys; infra/scripts/store-aws-key-in-databricks.ps1 creates them
# straight into the Databricks secret scope.
#
#   simulator: publishes each day's data into the sources (and reads the pre-generated year)
#   pipelines: what the owner's bronze jobs use; read-only, no simulator access

locals {
  parameter_arn   = "arn:aws:ssm:${local.region}:${local.account_id}:parameter${var.parameter_prefix}"
  shared_host_arn = "arn:aws:ssm:${local.region}:${local.account_id}:parameter${var.shared_sftp_host_parameter}"
  sources_arn     = aws_s3_bucket.this["sources"].arn
  simulator_arn   = aws_s3_bucket.this["simulator"].arn
  shared_rds_arn  = data.aws_db_instance.shared.db_instance_arn
  shared_sftp_arn = data.aws_instance.shared_sftp.arn

  # Both users may wake the shared servers when they run outside the daily window.
  wake_sources = [
    {
      Effect   = "Allow"
      Action   = ["rds:StartDBInstance", "rds:DescribeDBInstances"]
      Resource = local.shared_rds_arn
    },
    {
      Effect   = "Allow"
      Action   = "ec2:StartInstances"
      Resource = local.shared_sftp_arn
    },
    {
      Effect   = "Allow"
      Action   = "ec2:DescribeInstances"
      Resource = "*"
    },
    {
      Effect   = "Allow"
      Action   = "ssm:GetParameter"
      Resource = local.shared_host_arn
    },
  ]

  # An allow-list rather than the whole path: the pipelines must not read the owner password
  # or learn the simulator bucket, and a path-level grant would expose both.
  pipeline_parameters = [
    "aws/region",
    "postgres/host", "postgres/port", "postgres/database", "postgres/schema",
    "postgres/reader_username", "postgres/reader_password",
    "activity_api/url", "activity_api/api_key",
    "s3/sources_bucket",
    "sftp/username", "sftp/port", "sftp/private_key", "sftp/host_parameter",
    "rds/instance_identifier", "sftp/instance_id",
  ]
}

resource "aws_iam_user" "simulator" {
  name = "${local.p}-databricks-simulator"
}

resource "aws_iam_user_policy" "simulator" {
  name = "publish-to-sources"
  user = aws_iam_user.simulator.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [local.sources_arn, local.simulator_arn]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["${local.sources_arn}/*", "${local.simulator_arn}/*"]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:BatchWriteItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
          "dynamodb:GetItem", "dynamodb:DescribeTable",
        ]
        Resource = aws_dynamodb_table.segments.arn
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
        Resource = [local.parameter_arn, "${local.parameter_arn}/*"]
      },
    ], local.wake_sources)
  })
}

resource "aws_iam_user" "pipelines" {
  name = "${local.p}-databricks-pipelines"
}

# A managed policy, not an inline one: the parameter allow-list is longer than the 2,048
# characters an inline user policy may hold.
resource "aws_iam_policy" "pipelines" {
  name        = "${local.p}-pipelines-read-sources"
  description = "Read-only access to SupportHub's sources for the Databricks pipelines"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = local.sources_arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${local.sources_arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Resource = [for name in local.pipeline_parameters : "${local.parameter_arn}/${name}"]
      },
    ], local.wake_sources)
  })
}

resource "aws_iam_user_policy_attachment" "pipelines" {
  user       = aws_iam_user.pipelines.name
  policy_arn = aws_iam_policy.pipelines.arn
}
