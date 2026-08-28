[CmdletBinding()]
param(
    [string]$BackupDirectory = "",
    [string]$BackupName = "",
    [string]$HostName = "",
    [int]$Port = 5432,
    [string]$Database = "",
    [string]$Username = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "ops-common.ps1")

$repoRoot = Resolve-AbsolutePath (Join-Path $PSScriptRoot "..")
$targetDirectory = Get-RequiredSetting -Value $BackupDirectory -EnvironmentName "MOSAIC_POSTGRES_BACKUP_DIRECTORY"
$targetDirectory = Assert-SafeDirectory -Path $targetDirectory -RepoRoot $repoRoot
$HostName = Get-RequiredSetting -Value $HostName -EnvironmentName "PGHOST"
$Database = Get-RequiredSetting -Value $Database -EnvironmentName "PGDATABASE"
$Username = Get-RequiredSetting -Value $Username -EnvironmentName "PGUSER"
$password = Get-RequiredSetting -Value "" -EnvironmentName "MOSAIC_POSTGRES_PASSWORD"

if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535"
}
if ([string]::IsNullOrWhiteSpace($BackupName)) {
    $BackupName = "mosaic-postgres-" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
}
if ($BackupName -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') {
    throw "BackupName contains unsupported characters"
}

$dumpPath = Join-Path $targetDirectory ($BackupName + ".dump")
$manifestPath = Join-Path $targetDirectory ($BackupName + ".manifest.json")
if (((Test-Path -LiteralPath $dumpPath -PathType Leaf) -or (Test-Path -LiteralPath $manifestPath -PathType Leaf)) -and -not $Force) {
    throw "backup target already exists; use -Force only for this exact named backup"
}

$oldPassword = Set-ChildSecret -EnvironmentName "PGPASSWORD" -Value $password
try {
    try {
        $result = Invoke-CheckedNative -Name "pg_dump" -FilePath "pg_dump" -Arguments @(
            "--format=custom",
            "--file", $dumpPath,
            "--no-owner",
            "--no-privileges",
            "--host", $HostName,
            "--port", [string]$Port,
            "--username", $Username,
            "--dbname", $Database,
            "--verbose"
        )
    } catch {
        if (Test-Path -LiteralPath $dumpPath -PathType Leaf) {
            Remove-Item -LiteralPath $dumpPath -Force
        }
        throw
    }
} finally {
    Restore-ChildSecret -EnvironmentName "PGPASSWORD" -OldValue $oldPassword
}

$dumpItem = Get-Item -LiteralPath $dumpPath
if ($dumpItem.Length -le 0) {
    Remove-Item -LiteralPath $dumpPath -Force
    throw "pg_dump produced an empty backup"
}
$hash = Get-FileDigest -Path $dumpPath
$manifest = [ordered]@{
    schema_version = 1
    operation = "postgres-logical-backup"
    created_at_utc = [DateTime]::UtcNow.ToString("o")
    backup_file = Split-Path -Leaf $dumpPath
    bytes = $dumpItem.Length
    sha256 = $hash
    database = [ordered]@{
        host = $HostName
        port = $Port
        database = $Database
        username = $Username
    }
    command_output_sha256 = $result.output_sha256
}
Write-SafeJson -Value $manifest -Path $manifestPath
Write-Output (@{
    status = "ok"
    backup_file = $dumpPath
    manifest_file = $manifestPath
    sha256 = $hash
} | ConvertTo-Json -Compress)
