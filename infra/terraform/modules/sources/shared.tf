# The servers SupportHub shares with RetailPulse. RetailPulse's Terraform owns them, including
# their 06:00 to 08:00 UTC start/stop window; this stack only reads them.

data "aws_db_instance" "shared" {
  db_instance_identifier = var.shared_rds_identifier
}

data "aws_instance" "shared_sftp" {
  filter {
    name   = "tag:Name"
    values = [var.shared_sftp_name_tag]
  }
  filter {
    name   = "instance-state-name"
    values = ["pending", "running", "stopping", "stopped"]
  }
}

data "aws_ssm_parameter" "shared_admin_username" {
  name = "/retailpulse/dev/postgres/username"
}

data "aws_ssm_parameter" "shared_admin_password" {
  name = "/retailpulse/dev/postgres/password"
}
