# Dev environment: SupportHub's source systems.
#
#   terraform -chdir=infra/terraform/envs/dev init -backend-config=backend.hcl
#   terraform -chdir=infra/terraform/envs/dev plan
#
# State goes into the same state bucket as RetailPulse (same account), under its own key.
# backend.hcl is git-ignored; copy it from backend.hcl.example.
# The shared RetailPulse RDS instance must be running for plan and apply (06:00 to 08:00 UTC).

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {
    key          = "supporthub/dev/sources.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = "supporthub"
      Environment = "dev"
      ManagedBy   = "terraform"
    }
  }
}

module "sources" {
  source = "../../modules/sources"

  name_prefix                = "supporthub-dev"
  parameter_prefix           = "/supporthub/dev"
  shared_rds_identifier      = "retailpulse-dev-orders"
  shared_sftp_name_tag       = "retailpulse-dev-sftp"
  shared_sftp_host_parameter = "/retailpulse/dev/sftp/host"
  activity_api_source_dir    = "${path.root}/../../../../services/activity_api"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

output "sources" {
  value = module.sources
}
