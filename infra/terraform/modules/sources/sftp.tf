# A second SFTP user on RetailPulse's server. The server's sshd already chroots every member of
# the `sftponly` group to /sftp/<user> and reads keys from /etc/ssh/authorized_keys/<user>, so
# adding a user is all it takes. SSM Run Command does it on the instance; the association runs
# again whenever the instance comes back online, and the script is safe to repeat.

resource "tls_private_key" "sftp" {
  algorithm = "ED25519"
}

locals {
  sftp_user = "supporthub"
  sftp_setup = join("\n", [
    "set -euo pipefail",
    "id ${local.sftp_user} >/dev/null 2>&1 || useradd -g sftponly -s /sbin/nologin -M -d /data ${local.sftp_user}",
    "mkdir -p /sftp/${local.sftp_user}/data/wfm/forecasts /sftp/${local.sftp_user}/data/wfm/schedules /sftp/${local.sftp_user}/data/wfm/remediation /sftp/${local.sftp_user}/data/archive",
    "chown root:root /sftp/${local.sftp_user}",
    "chmod 755 /sftp/${local.sftp_user}",
    "chown -R ${local.sftp_user}:sftponly /sftp/${local.sftp_user}/data",
    "echo '${trimspace(tls_private_key.sftp.public_key_openssh)}' > /etc/ssh/authorized_keys/${local.sftp_user}",
    "chmod 644 /etc/ssh/authorized_keys/${local.sftp_user}",
  ])
}

resource "aws_ssm_association" "sftp_user" {
  name             = "AWS-RunShellScript"
  association_name = "${local.p}-sftp-user"

  targets {
    key    = "InstanceIds"
    values = [data.aws_instance.shared_sftp.id]
  }

  parameters = {
    commands = local.sftp_setup
  }
}
