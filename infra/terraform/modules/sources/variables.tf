variable "name_prefix" {
  description = "Prefix for every resource name, e.g. supporthub-dev"
  type        = string
}

variable "parameter_prefix" {
  description = "SSM Parameter Store path for connection details, e.g. /supporthub/dev"
  type        = string
}

variable "shared_rds_identifier" {
  description = "Identifier of the RetailPulse RDS instance that also hosts the CaseDesk database"
  type        = string
}

variable "shared_sftp_name_tag" {
  description = "Name tag of the RetailPulse SFTP server that also hosts the SupportHub SFTP user"
  type        = string
}

variable "shared_sftp_host_parameter" {
  description = "Parameter the shared SFTP server writes its current public IP to at every boot"
  type        = string
}

variable "activity_api_source_dir" {
  description = "Folder with the activity tracker API Lambda code"
  type        = string
}
