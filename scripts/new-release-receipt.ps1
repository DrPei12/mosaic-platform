[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")),
    [string]$OutputPath = "output/release/receipt.json",
    [string]$EvidencePath,
    [string]$BaselineCommit,
    [string]$MigrationHead,
    [string]$ConfigPath = "infra/compose/production.env.example",
    [switch]$RequireConfigHmac,
    [string]$ImageDigestPath,
    [switch]$RequireImageDigests,
    [string]$ProviderEvidencePath,
    [switch]$RequireProviderEvidence
)

$ErrorActionPreference = "Stop"

function Resolve-RepoPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $candidate = if ([IO.Path]::IsPathRooted($Path)) {
        $Path
    } else {
        Join-Path $RepoRoot $Path
    }
    return [IO.Path]::GetFullPath($candidate)
}

function Invoke-CheckedNative {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )

    $command = Get-Command $FilePath -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "$Name is unavailable"
    }
    $captured = @(& $command.Source @Arguments 2>&1 | ForEach-Object { [string]$_ })
    $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    $output = ($captured -join [Environment]::NewLine)
    if ($exitCode -ne 0) {
        throw "$Name failed with exit code $exitCode"
    }
    return [ordered]@{
        name = $Name
        exit_code = $exitCode
        output = $output
        output_sha256 = [Convert]::ToHexString(
            [Security.Cryptography.SHA256]::HashData(
                [Text.Encoding]::UTF8.GetBytes($output)
            )
        ).ToLowerInvariant()
        output_line_count = if ([string]::IsNullOrEmpty($output)) { 0 } else { ($output -split "`r?`n").Count }
    }
}

function Get-RelativePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    try {
        return [IO.Path]::GetRelativePath($RepoRoot, $Path).Replace("\", "/")
    } catch {
        return $Path
    }
}

function Get-ConfigHmac {
    param([Parameter(Mandatory = $true)][string]$Path)

    $composePath = Resolve-RepoPath "infra/compose/docker-compose.production.yml"
    if (-not (Test-Path -LiteralPath $composePath -PathType Leaf)) {
        throw "production compose is required for the config HMAC"
    }
    $configBytes = [IO.File]::ReadAllBytes($Path)
    $composeBytes = [IO.File]::ReadAllBytes($composePath)
    $configSha256 = [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData($configBytes)
    ).ToLowerInvariant()
    $composeSha256 = [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData($composeBytes)
    ).ToLowerInvariant()
    $key = [Environment]::GetEnvironmentVariable("MOSAIC_RELEASE_HMAC_KEY")
    if ([string]::IsNullOrWhiteSpace($key)) {
        if ($RequireConfigHmac) {
            throw "MOSAIC_RELEASE_HMAC_KEY is required for a full release receipt"
        }
        [Array]::Clear($configBytes, 0, $configBytes.Length)
        [Array]::Clear($composeBytes, 0, $composeBytes.Length)
        return [ordered]@{
            status = "NOT_RUN_ENVIRONMENT"
            sha256 = $null
            config_sha256 = $configSha256
            compose_sha256 = $composeSha256
        }
    }
    if ($key -match '(?i)REPLACE_WITH|placeholder') {
        throw "MOSAIC_RELEASE_HMAC_KEY must not use the example placeholder"
    }
    if ($key.Length -lt 32) {
        throw "MOSAIC_RELEASE_HMAC_KEY must contain at least 32 characters"
    }
    $keyBytes = [Text.Encoding]::UTF8.GetBytes($key)
    $separator = [Text.Encoding]::UTF8.GetBytes("`n--- mosaic production compose ---`n")
    $payload = [byte[]]::new($configBytes.Length + $separator.Length + $composeBytes.Length)
    [Array]::Copy($configBytes, 0, $payload, 0, $configBytes.Length)
    [Array]::Copy($separator, 0, $payload, $configBytes.Length, $separator.Length)
    [Array]::Copy($composeBytes, 0, $payload, $configBytes.Length + $separator.Length, $composeBytes.Length)
    $hmac = [Security.Cryptography.HMACSHA256]::new($keyBytes)
    try {
        $digest = $hmac.ComputeHash($payload)
    } finally {
        $hmac.Dispose()
        [Array]::Clear($keyBytes, 0, $keyBytes.Length)
    }
    [Array]::Clear($configBytes, 0, $configBytes.Length)
    [Array]::Clear($composeBytes, 0, $composeBytes.Length)
    [Array]::Clear($separator, 0, $separator.Length)
    [Array]::Clear($payload, 0, $payload.Length)
    return [ordered]@{
        status = "PASS"
        sha256 = [Convert]::ToHexString($digest).ToLowerInvariant()
        config_sha256 = $configSha256
        compose_sha256 = $composeSha256
    }
}

function Get-ImageDigestData {
    param(
        [string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedCommit
    )

    $requiredServices = @(
        "web", "api", "chat-relay", "generation-relay", "chat-worker",
        "image-audio-worker", "video-worker", "artifact-cleanup"
    )
    if ([string]::IsNullOrWhiteSpace($Path)) {
        if ($RequireImageDigests) {
            throw "an image digest manifest is required for a full release receipt"
        }
        return [ordered]@{
            status = "NOT_RUN_ENVIRONMENT"
            manifest = $null
            digests = $null
        }
    }
    $resolved = Resolve-RepoPath $Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "image digest manifest does not exist"
    }
    $manifest = Get-Content -LiteralPath $resolved -Raw | ConvertFrom-Json
    if (
        $manifest.schema_version -ne 1 -or
        $null -eq $manifest.image_digests -or
        [string]$manifest.commit -ne $ExpectedCommit
    ) {
        throw "image digest manifest schema is invalid"
    }
    $digests = [ordered]@{}
    $refs = [ordered]@{}
    foreach ($service in $requiredServices) {
        $property = $manifest.image_digests.PSObject.Properties[$service]
        if ($null -eq $property -or [string]$property.Value -notmatch '^sha256:[0-9a-f]{64}$') {
            throw "image digest is missing or invalid for service $service"
        }
        $digests[$service] = [string]$property.Value
        if ($null -ne $manifest.image_refs) {
            $refProperty = $manifest.image_refs.PSObject.Properties[$service]
            if ($null -eq $refProperty -or [string]::IsNullOrWhiteSpace([string]$refProperty.Value)) {
                throw "image reference is missing for service $service"
            }
            $refs[$service] = [string]$refProperty.Value
        }
    }
    return [ordered]@{
        status = "PASS"
        manifest = Get-RelativePath $resolved
        manifest_sha256 = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
        digests = $digests
        refs = if ($refs.Count -eq 0) { $null } else { $refs }
    }
}

function ConvertTo-CanonicalObject {
    param([AllowNull()][object]$Value)

    if ($null -eq $Value -or $Value -is [string] -or $Value.GetType().IsValueType) {
        return $Value
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $ordered = [ordered]@{}
        [string[]]$keys = @($Value.Keys | ForEach-Object { [string]$_ })
        [Array]::Sort($keys, [StringComparer]::Ordinal)
        foreach ($key in $keys) {
            $ordered[$key] = ConvertTo-CanonicalObject $Value[$key]
        }
        return $ordered
    }
    if ($Value -is [pscustomobject]) {
        $ordered = [ordered]@{}
        [string[]]$keys = @($Value.PSObject.Properties.Name)
        [Array]::Sort($keys, [StringComparer]::Ordinal)
        foreach ($key in $keys) {
            $ordered[$key] = ConvertTo-CanonicalObject $Value.$key
        }
        return $ordered
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $items = @($Value | ForEach-Object { ConvertTo-CanonicalObject $_ })
        return ,$items
    }
    return [string]$Value
}

function ConvertTo-CanonicalJson {
    param([Parameter(Mandatory = $true)][object]$Value)

    return (ConvertTo-CanonicalObject $Value | ConvertTo-Json -Depth 30 -Compress)
}

function Get-ProviderEvidenceData {
    param(
        [string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedCommit
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        if ($RequireProviderEvidence) {
            throw "signed Provider evidence is required for a full release receipt"
        }
        return [ordered]@{ status = "NOT_RUN"; source = $null; sha256 = $null }
    }
    $resolved = Resolve-RepoPath $Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "Provider evidence does not exist"
    }
    $payload = Get-Content -LiteralPath $resolved -Raw | ConvertFrom-Json
    if (
        $payload.live -ne $true -or
        [string]$payload.status -ne "ok" -or
        [string]$payload.source_commit -ne $ExpectedCommit -or
        $payload.source_tree_clean -ne $true -or
        [string]$payload.evidence_hmac_sha256 -notmatch '^[0-9a-f]{64}$'
    ) {
        throw "Provider evidence summary is invalid or belongs to another commit"
    }
    return [ordered]@{
        status = "PASS"
        source = Get-RelativePath $resolved
        sha256 = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Get-ReceiptHmac {
    param([Parameter(Mandatory = $true)][System.Collections.IDictionary]$Receipt)

    $key = [Environment]::GetEnvironmentVariable("MOSAIC_RELEASE_HMAC_KEY")
    if ([string]::IsNullOrWhiteSpace($key)) {
        if ($RequireConfigHmac) {
            throw "MOSAIC_RELEASE_HMAC_KEY is required for receipt integrity"
        }
        return [ordered]@{ status = "NOT_RUN_ENVIRONMENT"; sha256 = $null }
    }
    if ($key -match '(?i)REPLACE_WITH|placeholder') {
        throw "MOSAIC_RELEASE_HMAC_KEY must not use the example placeholder"
    }
    if ($key.Length -lt 32) {
        throw "MOSAIC_RELEASE_HMAC_KEY must contain at least 32 characters"
    }
    $keyBytes = [Text.Encoding]::UTF8.GetBytes($key)
    $payload = [Text.Encoding]::UTF8.GetBytes((ConvertTo-CanonicalJson $Receipt))
    $hmac = [Security.Cryptography.HMACSHA256]::new($keyBytes)
    try {
        $digest = $hmac.ComputeHash($payload)
    } finally {
        $hmac.Dispose()
        [Array]::Clear($keyBytes, 0, $keyBytes.Length)
        [Array]::Clear($payload, 0, $payload.Length)
    }
    return [ordered]@{
        status = "PASS"
        sha256 = [Convert]::ToHexString($digest).ToLowerInvariant()
    }
}

$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
Set-Location -LiteralPath $RepoRoot

$resolvedConfigPath = Resolve-RepoPath $ConfigPath
if (-not (Test-Path -LiteralPath $resolvedConfigPath -PathType Leaf)) {
    throw "config path does not exist"
}

$gitCommit = Invoke-CheckedNative -Name "git rev-parse HEAD" -FilePath "git" -Arguments @("rev-parse", "HEAD")
$gitStatus = Invoke-CheckedNative -Name "git status" -FilePath "git" -Arguments @("status", "--short", "--branch", "--untracked-files=all")
$dirtyLines = @(
    $gitStatus.output -split "`r?`n" |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and $_ -notmatch '^##(?:\s|$)' }
)

$lockFiles = @(
    "pnpm-lock.yaml",
    "apps/api/uv.lock"
)
$lockHashes = [ordered]@{}
foreach ($lockFile in $lockFiles) {
    $resolvedLock = Resolve-RepoPath $lockFile
    if (-not (Test-Path -LiteralPath $resolvedLock -PathType Leaf)) {
        throw "lock file does not exist: $lockFile"
    }
    $lockHashes[$lockFile] = (Get-FileHash -LiteralPath $resolvedLock -Algorithm SHA256).Hash.ToLowerInvariant()
}

$evidence = [ordered]@{
    commands = @()
    tests = @()
    limitations = @()
}
if (-not [string]::IsNullOrWhiteSpace($EvidencePath)) {
    $resolvedEvidence = Resolve-RepoPath $EvidencePath
    if (-not (Test-Path -LiteralPath $resolvedEvidence -PathType Leaf)) {
        throw "evidence path does not exist"
    }
    $loadedEvidence = Get-Content -LiteralPath $resolvedEvidence -Raw | ConvertFrom-Json
    if ($null -ne $loadedEvidence.commands) { $evidence.commands = @($loadedEvidence.commands) }
    if ($null -ne $loadedEvidence.tests) { $evidence.tests = @($loadedEvidence.tests) }
    if ($null -ne $loadedEvidence.limitations) { $evidence.limitations = @($loadedEvidence.limitations) }
}

$hmacResult = Get-ConfigHmac -Path $resolvedConfigPath
$commit = $gitCommit.output.Trim()
$imageDigestResult = Get-ImageDigestData -Path $ImageDigestPath -ExpectedCommit $commit
$providerEvidenceResult = Get-ProviderEvidenceData -Path $ProviderEvidencePath -ExpectedCommit $commit
$requiredPassingTests = @(
    "release-static-contracts",
    "migration-head",
    "production-compose-config",
    "production-image-digests",
    "production-web-image-startup",
    "provider-live-evidence",
    "web lint",
    "web typecheck",
    "web boundaries",
    "workspace package tests",
    "web Vitest",
    "web standalone build",
    "pnpm verify:api",
    "postgres-row-lock"
)
$passingTestNames = @(
    $evidence.tests |
        Where-Object { $_.status -eq "PASS" } |
        ForEach-Object { [string]$_.name }
)
$allRequiredTestsPassed = @(
    $requiredPassingTests | Where-Object { $_ -notin $passingTestNames }
).Count -eq 0
$receipt = [ordered]@{
    schema_version = 1
    receipt_hmac_schema = "mosaic_release_receipt_v1"
    acceptance_status = if (
        $dirtyLines.Count -eq 0 -and
        $hmacResult.status -eq "PASS" -and
        $imageDigestResult.status -eq "PASS" -and
        $providerEvidenceResult.status -eq "PASS" -and
        $RequireConfigHmac -and
        $RequireImageDigests -and
        $RequireProviderEvidence -and
        @($evidence.limitations).Count -eq 0 -and
        $allRequiredTestsPassed -and
        @($evidence.tests | Where-Object { $_.status -ne "PASS" }).Count -eq 0
    ) { "PASS" } else { "BOUNDED" }
    generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    repository = (Split-Path -Leaf $RepoRoot)
    baseline_commit = if ([string]::IsNullOrWhiteSpace($BaselineCommit)) { $null } else { $BaselineCommit }
    commit = $commit
    clean_tree = ($dirtyLines.Count -eq 0)
    migration_head = if ([string]::IsNullOrWhiteSpace($MigrationHead)) { $null } else { $MigrationHead }
    lock_hashes = $lockHashes
    config_source = Get-RelativePath $resolvedConfigPath
    config_sha256 = $hmacResult.config_sha256
    compose_sha256 = $hmacResult.compose_sha256
    config_hmac_status = $hmacResult.status
    config_hmac_sha256 = $hmacResult.sha256
    image_digest_status = $imageDigestResult.status
    image_digest_manifest = $imageDigestResult.manifest
    image_digest_manifest_sha256 = $imageDigestResult.manifest_sha256
    image_refs = $imageDigestResult.refs
    image_digests = $imageDigestResult.digests
    provider_evidence_status = $providerEvidenceResult.status
    provider_evidence_source = $providerEvidenceResult.source
    provider_evidence_sha256 = $providerEvidenceResult.sha256
    commands = @($evidence.commands)
    tests = @($evidence.tests)
    limitations = @($evidence.limitations)
}
$receiptHmac = Get-ReceiptHmac -Receipt $receipt
$receipt.receipt_hmac_status = $receiptHmac.status
$receipt.receipt_hmac_sha256 = $receiptHmac.sha256

$fullOutputPath = Resolve-RepoPath $OutputPath
$outputDirectory = Split-Path -Parent $fullOutputPath
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $fullOutputPath -Encoding utf8
Write-Output ("receipt: " + (Get-RelativePath $fullOutputPath))
