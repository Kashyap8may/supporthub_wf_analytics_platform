# SupportHub's four source systems. To keep cost down they share two servers with the
# RetailPulse project in the same account (see docs/HANDOFF.md):
#   shared.tf      looks up RetailPulse's RDS instance and SFTP server
#   postgres.tf    a `supporthub` database, owner and read-only logins, schema `casedesk` on that RDS
#   sftp.tf        a chrooted, key-only `supporthub` SFTP user on that EC2 server (SSM Run Command)
#   activity_api.tf DynamoDB + Lambda + API Gateway for the activity tracker
#   s3.tf          the HR/QC file drop and a private bucket for the simulator
#   iam.tf         users for the Databricks simulator and pipelines (no access keys)
#   parameters.tf  connection details in SSM Parameter Store under /supporthub/dev
# The AWS Budgets alert in RetailPulse already covers the whole account.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    postgresql = {
      source  = "cyrilgdn/postgresql"
      version = "~> 1.25"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.region
  p          = var.name_prefix
}
