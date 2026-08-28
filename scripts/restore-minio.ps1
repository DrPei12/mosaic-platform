[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SourceDirectory,
    [string]$Endpoint = "",
    [string]$Bucket = "",
    [string]$AccessKey = "",
    [string]$SecretKey = "",
    [string]$Alias = "mosaicrestore",
    [switch]$AllowOverwrite
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "ops-common.ps1")

if (-not $AllowOverwrite) {
    throw "restore overwrites objects; pass -AllowOverwrite for the exact target bucket"
}
if ($Alias -notmatch '^[A-Za-z][A-Za-z0-9_-]{0,31}$') {
    throw "Alias contains unsupported characters"
}
$sourcePath = Assert-SafeInputFile -Path (Join-Path $SourceDirectory "minio-mirror.manifest.json") | Split-Path -Parent
$manifest = Get-Content -LiteralPath (Join-Path $sourcePath "minio-mirror.manifest.json") -Raw | ConvertFrom-Json
if ($manifest.schema_version -ne 1 -or $manifest.operation -ne "minio-mirror") {
    throw "MinIO mirror manifest schema is invalid"
}
$sourceFiles = @(Get-ChildItem -LiteralPath $sourcePath -File -Recurse | Where-Object { $_.Name -ne "minio-mirror.manifest.json" })
$sourceFileCount = 0
if ($null -eq $manifest.file_count -or [int]::TryParse([string]$manifest.file_count, [ref]$sourceFileCount) -eq $false -or $sourceFileCount -lt 0) {
    throw "MinIO mirror manifest file_count is invalid"
}
if ($sourceFiles.Count -ne $sourceFileCount) {
    throw "MinIO mirror files do not match its manifest"
}
if ($null -ne $manifest.total_bytes) {
    $expectedBytes = [long]$manifest.total_bytes
    $actualBytes = [long](($sourceFiles | Measure-Object -Property Length -Sum).Sum)
    if ($actualBytes -ne $expectedBytes) {
        throw "MinIO mirror bytes do not match its manifest"
    }
}
$Endpoint = Get-RequiredSetting -Value $Endpoint -EnvironmentName "MOSAIC_MINIO_ENDPOINT"
$Bucket = Get-RequiredSetting -Value $Bucket -EnvironmentName "MOSAIC_MINIO_BUCKET"
$AccessKey = Get-RequiredSetting -Value $AccessKey -EnvironmentName "MOSAIC_MINIO_ACCESS_KEY_ID"
$SecretKey = Get-RequiredSetting -Value $SecretKey -EnvironmentName "MOSAIC_MINIO_SECRET_ACCESS_KEY"
$mcState = Set-McHostEnvironment -Alias $Alias -Endpoint $Endpoint -AccessKey $AccessKey -SecretKey $SecretKey
try {
    $restoreResult = Invoke-CheckedNative -Name "mc mirror restore" -FilePath "mc" -Arguments @(
        "mirror", "--overwrite", "--preserve", "--exclude", "minio-mirror.manifest.json", "--json", $sourcePath, ("{0}/{1}" -f $Alias, $Bucket)
    )
} finally {
    Restore-McHostEnvironment -State $mcState
}

Write-Output (@{
    status = "ok"
    source_directory = $sourcePath
    target_bucket = $Bucket
    source_file_count = $sourceFileCount
    restore_output_sha256 = $restoreResult.output_sha256
} | ConvertTo-Json -Compress)
