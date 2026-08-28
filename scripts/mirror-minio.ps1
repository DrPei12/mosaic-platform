[CmdletBinding()]
param(
    [string]$Endpoint = "",
    [string]$Bucket = "",
    [string]$AccessKey = "",
    [string]$SecretKey = "",
    [Parameter(Mandatory = $true)][string]$Destination,
    [string]$Alias = "mosaicbackup",
    [switch]$AllowOverwrite
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "ops-common.ps1")

if ($Alias -notmatch '^[A-Za-z][A-Za-z0-9_-]{0,31}$') {
    throw "Alias contains unsupported characters"
}
$Endpoint = Get-RequiredSetting -Value $Endpoint -EnvironmentName "MOSAIC_MINIO_ENDPOINT"
$Bucket = Get-RequiredSetting -Value $Bucket -EnvironmentName "MOSAIC_MINIO_BUCKET"
$AccessKey = Get-RequiredSetting -Value $AccessKey -EnvironmentName "MOSAIC_MINIO_ACCESS_KEY_ID"
$SecretKey = Get-RequiredSetting -Value $SecretKey -EnvironmentName "MOSAIC_MINIO_SECRET_ACCESS_KEY"
$destinationPath = Assert-SafeDirectory -Path $Destination -RepoRoot (Resolve-AbsolutePath (Join-Path $PSScriptRoot ".."))
if (-not $AllowOverwrite -and -not (Test-DirectoryEmpty -Path $destinationPath)) {
    throw "destination is not empty; pass -AllowOverwrite for this exact mirror directory"
}

$mcState = Set-McHostEnvironment -Alias $Alias -Endpoint $Endpoint -AccessKey $AccessKey -SecretKey $SecretKey
try {
    $mirrorResult = Invoke-CheckedNative -Name "mc mirror" -FilePath "mc" -Arguments @(
        "mirror", "--overwrite", "--preserve", "--json", ("{0}/{1}" -f $Alias, $Bucket), $destinationPath
    )
} finally {
    Restore-McHostEnvironment -State $mcState
}

$manifestPath = Join-Path $destinationPath "minio-mirror.manifest.json"
$mirroredFiles = @(Get-ChildItem -LiteralPath $destinationPath -File -Recurse | Where-Object { $_.Name -ne "minio-mirror.manifest.json" })
$manifest = [ordered]@{
    schema_version = 1
    operation = "minio-mirror"
    created_at_utc = [DateTime]::UtcNow.ToString("o")
    endpoint_host = ([Uri]$Endpoint).Host
    bucket = $Bucket
    destination = $destinationPath
    object_listing_output_sha256 = $mirrorResult.output_sha256
    file_count = $mirroredFiles.Count
    total_bytes = [long](($mirroredFiles | Measure-Object -Property Length -Sum).Sum)
}
Write-SafeJson -Value $manifest -Path $manifestPath
Write-Output (@{
    status = "ok"
    destination = $destinationPath
    manifest_file = $manifestPath
    file_count = $manifest.file_count
} | ConvertTo-Json -Compress)
