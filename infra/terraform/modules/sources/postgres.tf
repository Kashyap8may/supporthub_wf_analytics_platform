# CaseDesk lives in its own database on the shared RDS instance. Terraform connects with the
# instance's admin login (read from RetailPulse's parameters) to create the database, an owner
# login used by the simulator, and a read-only login for the pipelines. The RDS instance must be
# running when this is planned or applied (06:00 to 08:00 UTC, or `make sources-up` in RetailPulse).

provider "postgresql" {
  host            = data.aws_db_instance.shared.address
  port            = data.aws_db_instance.shared.port
  username        = data.aws_ssm_parameter.shared_admin_username.value
  password        = data.aws_ssm_parameter.shared_admin_password.value
  database        = "postgres"
  sslmode         = "require"
  connect_timeout = 20
  # RDS has no true superuser; the provider then grants itself role membership where needed.
  superuser = false
}

resource "random_password" "owner" {
  length  = 32
  special = false
}

resource "random_password" "reader" {
  length  = 32
  special = false
}

resource "postgresql_role" "owner" {
  name     = "supporthub_app"
  login    = true
  password = random_password.owner.result
}

resource "postgresql_role" "reader" {
  name     = "supporthub_reader"
  login    = true
  password = random_password.reader.result
}

resource "postgresql_database" "casedesk" {
  name  = "supporthub"
  owner = postgresql_role.owner.name
}

# Nobody else on the shared instance may connect to this database.
resource "postgresql_grant" "revoke_public_connect" {
  database    = postgresql_database.casedesk.name
  role        = "public"
  object_type = "database"
  privileges  = []
}

resource "postgresql_grant" "reader_connect" {
  database    = postgresql_database.casedesk.name
  role        = postgresql_role.reader.name
  object_type = "database"
  privileges  = ["CONNECT"]
}

resource "postgresql_schema" "casedesk" {
  name     = "casedesk"
  database = postgresql_database.casedesk.name
  owner    = postgresql_role.owner.name
}

resource "postgresql_grant" "reader_schema" {
  database    = postgresql_database.casedesk.name
  schema      = postgresql_schema.casedesk.name
  role        = postgresql_role.reader.name
  object_type = "schema"
  privileges  = ["USAGE"]
}

# Tables are created later by the publisher (as the owner), so grant SELECT on future tables.
resource "postgresql_default_privileges" "reader_tables" {
  database    = postgresql_database.casedesk.name
  schema      = postgresql_schema.casedesk.name
  owner       = postgresql_role.owner.name
  role        = postgresql_role.reader.name
  object_type = "table"
  privileges  = ["SELECT"]
}
