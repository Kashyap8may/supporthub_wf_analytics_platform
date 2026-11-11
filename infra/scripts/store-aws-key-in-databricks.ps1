# Creates an access key for one of the Databricks IAM users and stores it straight in a
# Databricks secret scope, so the secret is never printed or written to disk.
#
#   powershell -ExecutionPolicy Bypass -File infra\scripts\store-aws-key-in-databricks.ps1 -User pipelines
#   powershell -ExecutionPolicy Bypass -File infra\scripts\store-aws-key-in-databricks.ps1 -User simulator
#
# Needs `aws configure` and `databricks auth login`. Running it again rotates the key: the new
# key replaces the secret and the old key is deleted from IAM.

param(
    [Parameter(Mandatory)] [ValidateSet("pipelines", "simulator")] [string] $User,
    [string] $Scope = "supporthub-dev"
)

$ErrorActionPreference = "Stop"
$iamUser = "supporthub-dev-databricks-$User"
$prefix = if ($User -eq "pipelines") { "aws" } else { "aws_simulator" }

$scopes = databricks secrets list-scopes --output json | ConvertFrom-Json
if (-not ($scopes | Where-Object name -eq $Scope)) {
    databricks secrets create-scope $Scope
    Write-Host "Created secret scope $Scope"
}

$oldKeys = aws iam list-access-keys --user-name $iamUser --query "AccessKeyMetadata[].AccessKeyId" --output json | ConvertFrom-Json
$key = (aws iam create-access-key --user-name $iamUser --output json | ConvertFrom-Json).AccessKey
databricks secrets put-secret $Scope "${prefix}_access_key_id" --string-value $key.AccessKeyId
databricks secrets put-secret $Scope "${prefix}_secret_access_key" --string-value $key.SecretAccessKey
Remove-Variable key

foreach ($old in $oldKeys) {
    aws iam delete-access-key --user-name $iamUser --access-key-id $old
    Write-Host "Deleted old key $old"
}
Write-Host "Stored a new key for $iamUser in scope $Scope as ${prefix}_access_key_id / ${prefix}_secret_access_key"
