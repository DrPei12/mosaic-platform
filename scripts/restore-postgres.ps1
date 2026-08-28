[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BackupFile,
    [string]$HostName = "",
    [int]$Port = 5432,
    [Parameter(Mandatory = $true)][string]$TargetDatabase,
    [string]$Username = "",
    [switch]$AllowOverwrite
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "ops-common.ps1")

if (-not $AllowOverwrite) {
    throw "restore is destructive; pass -AllowOverwrite for the exact target database"
}
$backupPath = Assert-SafeInputFile -Path $BackupFile
$HostName = Get-RequiredSetting -Value $HostName -EnvironmentName "PGHOST"
$Username = Get-RequiredSetting -Value $Username -EnvironmentName "PGUSER"
$password = Get-RequiredSetting -Value "" -EnvironmentName "MOSAIC_POSTGRES_PASSWORD"
if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535"
}
if ([string]::IsNullOrWhiteSpace($TargetDatabase) -or $TargetDatabase -match '^(postgres|template[01])$' -or $TargetDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_$-]{0,62}$') {
    throw "TargetDatabase must be an explicit non-template database name"
}

$manifestPath = [IO.Path]::ChangeExtension($backupPath, ".manifest.json")
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "backup manifest is required next to the dump file"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schema_version -ne 1 -or $manifest.operation -ne "postgres-logical-backup") {
    throw "backup manifest schema is invalid"
}
if ($manifest.backup_file -ne (Split-Path -Leaf $backupPath)) {
    throw "backup manifest does not describe the requested dump"
}
if ($manifest.sha256 -ne (Get-FileDigest -Path $backupPath)) {
    throw "backup checksum does not match its manifest"
}
if ($null -eq $manifest.bytes -or [long]$manifest.bytes -ne (Get-Item -LiteralPath $backupPath).Length) {
    throw "backup byte count does not match its manifest"
}

$oldPassword = Set-ChildSecret -EnvironmentName "PGPASSWORD" -Value $password
try {
    Invoke-CheckedNative -Name "pg_restore list" -FilePath "pg_restore" -Arguments @(
        "--list", $backupPath
    ) | Out-Null
    $restoreResult = Invoke-CheckedNative -Name "pg_restore" -FilePath "pg_restore" -Arguments @(
        "--exit-on-error",
        "--single-transaction",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--host", $HostName,
        "--port", [string]$Port,
        "--username", $Username,
        "--dbname", $TargetDatabase,
        $backupPath
    )
} finally {
    Restore-ChildSecret -EnvironmentName "PGPASSWORD" -OldValue $oldPassword
}

Write-Output (@{
    status = "ok"
    target_database = $TargetDatabase
    backup_file = $backupPath
    backup_sha256 = $manifest.sha256
    restore_output_sha256 = $restoreResult.output_sha256
} | ConvertTo-Json -Compress)
