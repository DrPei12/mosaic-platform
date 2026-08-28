[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BackupFile,
    [Parameter(Mandatory = $true)][string]$MirrorDirectory,
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")),
    [string]$HostName = "",
    [Parameter(Mandatory = $true)][string]$TargetDatabase,
    [string]$Username = "",
    [int]$Port = 5432,
    [string]$MinioEndpoint = "",
    [string]$MinioBucket = "",
    [string]$MinioAccessKey = "",
    [string]$MinioSecretKey = "",
    [string]$MinioAlias = "mosaicverify",
    [string]$ExpectedMigrationHead = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "ops-common.ps1")

$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
if ([string]::IsNullOrWhiteSpace($ExpectedMigrationHead)) {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -eq $uv) {
        throw "uv is unavailable; pass -ExpectedMigrationHead explicitly"
    }
    Push-Location -LiteralPath $RepoRoot
    try {
        $headResult = Invoke-CheckedNative -Name "alembic heads" -FilePath $uv.Source -Arguments @(
            "run",
            "--project",
            "apps/api",
            "alembic",
            "-c",
            "apps/api/alembic.ini",
            "heads"
        )
    } finally {
        Pop-Location
    }
    $heads = @(
        $headResult.output -split "`r?`n" |
            Where-Object { $_ -match '^\s*([A-Za-z0-9_.-]+)\s+\(head\)\s*$' } |
            ForEach-Object { ([regex]::Match($_, '^\s*([A-Za-z0-9_.-]+)\s+\(head\)\s*$')).Groups[1].Value }
    )
    if ($heads.Count -ne 1) {
        throw "repository migration head check expected exactly one head"
    }
    $ExpectedMigrationHead = $heads[0]
}

$backupPath = Assert-SafeInputFile -Path $BackupFile
$manifestPath = [IO.Path]::ChangeExtension($backupPath, ".manifest.json")
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "backup manifest is required next to the dump file"
}
$backupManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($backupManifest.schema_version -ne 1 -or $backupManifest.operation -ne "postgres-logical-backup") {
    throw "backup manifest schema is invalid"
}
if ($backupManifest.sha256 -ne (Get-FileDigest -Path $backupPath)) {
    throw "backup checksum does not match its manifest"
}
if ($null -eq $backupManifest.bytes -or [long]$backupManifest.bytes -ne (Get-Item -LiteralPath $backupPath).Length) {
    throw "backup byte count does not match its manifest"
}
Invoke-CheckedNative -Name "pg_restore list" -FilePath "pg_restore" -Arguments @("--list", $backupPath) | Out-Null

$mirrorManifestPath = Assert-SafeInputFile -Path (Join-Path $MirrorDirectory "minio-mirror.manifest.json")
$mirrorDirectoryPath = Split-Path -Parent $mirrorManifestPath
$mirrorManifest = Get-Content -LiteralPath $mirrorManifestPath -Raw | ConvertFrom-Json
if ($mirrorManifest.schema_version -ne 1 -or $mirrorManifest.operation -ne "minio-mirror") {
    throw "MinIO mirror manifest schema is invalid"
}
$mirrorFileCount = 0
if ($null -eq $mirrorManifest.file_count -or [int]::TryParse([string]$mirrorManifest.file_count, [ref]$mirrorFileCount) -eq $false -or $mirrorFileCount -lt 0) {
    throw "MinIO mirror manifest file_count is invalid"
}
$mirrorFiles = @(Get-ChildItem -LiteralPath $mirrorDirectoryPath -File -Recurse | Where-Object { $_.Name -ne "minio-mirror.manifest.json" })
if ($mirrorFiles.Count -ne $mirrorFileCount) {
    throw "MinIO mirror file count does not match its manifest"
}
if ($null -ne $mirrorManifest.total_bytes) {
    $mirrorTotalBytes = [long]$mirrorManifest.total_bytes
    $actualTotalBytes = [long](($mirrorFiles | Measure-Object -Property Length -Sum).Sum)
    if ($actualTotalBytes -ne $mirrorTotalBytes) {
        throw "MinIO mirror byte count does not match its manifest"
    }
}

if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535"
}
$HostName = Get-RequiredSetting -Value $HostName -EnvironmentName "PGHOST"
$Username = Get-RequiredSetting -Value $Username -EnvironmentName "PGUSER"
$password = Get-RequiredSetting -Value "" -EnvironmentName "MOSAIC_POSTGRES_PASSWORD"
$oldPassword = Set-ChildSecret -EnvironmentName "PGPASSWORD" -Value $password
try {
    $postgresProbe = Invoke-CheckedNative -Name "psql restore verification" -FilePath "psql" -Arguments @(
        "--no-psqlrc",
        "--set", "ON_ERROR_STOP=1",
        "--tuples-only",
        "--no-align",
        "--quiet",
        "--host", $HostName,
        "--port", [string]$Port,
        "--username", $Username,
        "--dbname", $TargetDatabase,
        "--command", "SELECT version_num FROM alembic_version ORDER BY version_num;"
    )
} finally {
    Restore-ChildSecret -EnvironmentName "PGPASSWORD" -OldValue $oldPassword
}
$actualHeads = @($postgresProbe.output -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { $_.Trim() })
if ($actualHeads.Count -ne 1 -or $actualHeads[0] -ne $ExpectedMigrationHead) {
    throw "restored PostgreSQL migration head does not match the expected head"
}

$MinioEndpoint = Get-RequiredSetting -Value $MinioEndpoint -EnvironmentName "MOSAIC_MINIO_ENDPOINT"
$MinioBucket = Get-RequiredSetting -Value $MinioBucket -EnvironmentName "MOSAIC_MINIO_BUCKET"
$MinioAccessKey = Get-RequiredSetting -Value $MinioAccessKey -EnvironmentName "MOSAIC_MINIO_ACCESS_KEY_ID"
$MinioSecretKey = Get-RequiredSetting -Value $MinioSecretKey -EnvironmentName "MOSAIC_MINIO_SECRET_ACCESS_KEY"
if ($MinioAlias -notmatch '^[A-Za-z][A-Za-z0-9_-]{0,31}$') {
    throw "MinioAlias contains unsupported characters"
}
$mcState = Set-McHostEnvironment -Alias $MinioAlias -Endpoint $MinioEndpoint -AccessKey $MinioAccessKey -SecretKey $MinioSecretKey
try {
    $minioProbe = Invoke-CheckedNative -Name "mc restore verification" -FilePath "mc" -Arguments @(
        "ls", "--recursive", "--json", ("{0}/{1}" -f $MinioAlias, $MinioBucket)
    )
} finally {
    Restore-McHostEnvironment -State $mcState
}
$objectLines = @($minioProbe.output -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
if ($objectLines.Count -ne $mirrorFileCount) {
    throw "restored MinIO object count does not match the mirror manifest"
}

Write-Output (@{
    status = "ok"
    postgres_migration_head = $actualHeads[0]
    minio_object_count = $objectLines.Count
    mirror_file_count = $mirrorFileCount
    backup_sha256 = $backupManifest.sha256
} | ConvertTo-Json -Compress)
