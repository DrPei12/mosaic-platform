[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")),
    [string]$BaselineCommit = "19bc40fc243c32b2b7ae4ccfd3813c9221daef0e",
    [string]$ExpectedMigrationHead = "",
    [string]$ConfigPath = "infra/compose/production.env.example",
    [string]$ReceiptPath = "output/release/receipt.json",
    [Alias("DryRun")]
    [switch]$StaticOnly,
    [switch]$RunTests,
    [switch]$AllowDirty,
    [switch]$RequireConfigHmac,
    [switch]$BuildImages,
    [switch]$RequireImageDigests,
    [string]$ProviderEvidencePath,
    [switch]$RequireProviderEvidence
)

$ErrorActionPreference = "Stop"

function Resolve-RepoPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $candidate = if ([IO.Path]::IsPathRooted($Path)) { $Path } else { Join-Path $RepoRoot $Path }
    return [IO.Path]::GetFullPath($candidate)
}

function Test-NativeAvailable {
    param([Parameter(Mandatory = $true)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-CapturedNative {
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

function Add-CommandEvidence {
    param([Parameter(Mandatory = $true)][System.Collections.IDictionary]$Result)

    $script:commandEvidence.Add([ordered]@{
        name = $Result.name
        exit_code = $Result.exit_code
        output_sha256 = $Result.output_sha256
        output_line_count = $Result.output_line_count
    })
}

function Invoke-Required {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )

    $result = Invoke-CapturedNative -Name $Name -FilePath $FilePath -Arguments $Arguments
    Add-CommandEvidence -Result $result
    if ($result.exit_code -ne 0) {
        throw "$Name failed with exit code $($result.exit_code)"
    }
    return $result
}

function Add-Limitation {
    param([Parameter(Mandatory = $true)][string]$Value)
    $script:limitations.Add($Value)
}

function Assert-Contains {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Pattern,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if ($Text -notmatch $Pattern) {
        throw $Message
    }
}

function Assert-PowerShellSyntax {
    param([Parameter(Mandatory = $true)][string]$Path)

    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) {
        throw "PowerShell syntax check failed: $(Split-Path -Leaf $Path)"
    }
}

$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
Set-Location -LiteralPath $RepoRoot
$commandEvidence = [Collections.Generic.List[object]]::new()
$testEvidence = [Collections.Generic.List[object]]::new()
$limitations = [Collections.Generic.List[string]]::new()

$requiredFiles = @(
    ".dockerignore",
    "infra/docker/web.Dockerfile",
    "infra/docker/api.Dockerfile",
    "infra/compose/docker-compose.production.yml",
    "infra/compose/production.env.example",
    "infra/compose/staging.env.example",
    "infra/postgres/init/001-runtime-roles.sh",
    ".github/workflows/production-release.yml",
    "scripts/verify-release.ps1",
    "scripts/new-release-receipt.ps1",
    "scripts/verify-release-receipt.ps1",
    "scripts/ops-common.ps1",
    "scripts/backup-postgres.ps1",
    "scripts/restore-postgres.ps1",
    "scripts/mirror-minio.ps1",
    "scripts/restore-minio.ps1",
    "scripts/verify-restore.ps1",
    "apps/api/scripts/postgres_concurrency_gate.py",
    "apps/api/scripts/ensure_artifact_bucket.py",
    "apps/api/scripts/verify_live_evidence.py",
    "apps/api/app/catalog/live_evidence.py"
)
foreach ($file in $requiredFiles) {
    $resolved = Resolve-RepoPath $file
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "required release file is missing: $file"
    }
}

$nextConfig = Get-Content -LiteralPath (Resolve-RepoPath "apps/web/next.config.ts") -Raw
Assert-Contains -Text $nextConfig -Pattern 'output\s*:.*[" ]standalone[" ]' -Message "Next standalone output is not configured"
Assert-Contains -Text $nextConfig -Pattern 'outputFileTracingRoot' -Message "Next standalone tracing root is not configured for the monorepo"
Assert-Contains -Text $nextConfig -Pattern '@swc\+helpers@\*' -Message "Next standalone output must include the complete SWC helper runtime"

$webDockerfile = Get-Content -LiteralPath (Resolve-RepoPath "infra/docker/web.Dockerfile") -Raw
$apiDockerfile = Get-Content -LiteralPath (Resolve-RepoPath "infra/docker/api.Dockerfile") -Raw
Assert-Contains -Text $webDockerfile -Pattern '(?m)^USER\s+mosaic\s*$' -Message "web runtime must run as mosaic"
Assert-Contains -Text $webDockerfile -Pattern 'apps/web/server\.js' -Message "web runtime must use the monorepo standalone server"
Assert-Contains -Text $webDockerfile -Pattern 'NODE_OPTIONS=--no-experimental-require-module' -Message "web runtime must disable the Node module-sync condition"
Assert-Contains -Text $webDockerfile -Pattern 'ARG MOSAIC_API_ORIGIN' -Message "web build must accept MOSAIC_API_ORIGIN"
Assert-Contains -Text $webDockerfile -Pattern 'ENV MOSAIC_API_ORIGIN=' -Message "web build must export MOSAIC_API_ORIGIN"
Assert-Contains -Text $apiDockerfile -Pattern '(?m)^USER\s+mosaic\s*$' -Message "api runtime must run as mosaic"
Assert-Contains -Text $apiDockerfile -Pattern 'MOSAIC_SOURCE_COMMIT' -Message "api image must carry its immutable source commit"
if ($apiDockerfile -match '(?m)^USER\s+root\s*$' -or $webDockerfile -match '(?m)^USER\s+root\s*$') {
    throw "release Dockerfiles must not leave the runtime as root"
}

$compose = Get-Content -LiteralPath (Resolve-RepoPath "infra/compose/docker-compose.production.yml") -Raw
$expectedServices = @(
    "postgres", "redis", "rabbitmq", "minio", "minio-ready", "migration", "seed-catalog", "seed-storage", "api", "web",
    "chat-relay", "generation-relay", "chat-worker", "image-audio-worker", "video-worker", "artifact-cleanup"
)
foreach ($service in $expectedServices) {
    Assert-Contains -Text $compose -Pattern ("(?m)^  " + [regex]::Escape($service) + ":\s*$") -Message "production compose is missing service $service"
}
if ($compose -match '(?m)^\s+secrets\s*:') {
    throw "production compose must inject secrets through environment variables only"
}
$serviceBlocks = [regex]::Matches($compose, '(?ms)^  (?<name>[a-z][a-z0-9-]*):\s*\r?\n(?<body>.*?)(?=^  [a-z][a-z0-9-]*:\s*$|\z)')
$publishedServices = @(
    $serviceBlocks | Where-Object { $_.Groups["body"].Value -match '(?m)^\s+ports\s*:' } | ForEach-Object { $_.Groups["name"].Value }
)
if ($publishedServices.Count -ne 1 -or $publishedServices[0] -ne "web") {
    throw "only the web service may publish host ports"
}
if ($compose -notmatch '(?m)^volumes:\s*$' -or $compose -notmatch 'mosaic_production_postgres') {
    throw "production compose must declare persistent volumes"
}
Assert-Contains -Text $compose -Pattern 'server.*?/data' -Message "production MinIO must be started with an explicit server command"
Assert-Contains -Text $compose -Pattern 'curlimages/curl' -Message "MinIO readiness must use an explicit curl sidecar"
Assert-Contains -Text $compose -Pattern 'entrypoint:.*?curl' -Message "MinIO readiness sidecar must set an explicit curl entrypoint"
Assert-Contains -Text $compose -Pattern 'ensure_artifact_bucket\.py' -Message "production compose must verify the artifact bucket before workers"
Assert-Contains -Text $compose -Pattern 'MOSAIC_API_DATABASE_URL' -Message "API must use a dedicated RLS-scoped database URL"
Assert-Contains -Text $compose -Pattern 'MOSAIC_OWNER_DATABASE_URL' -Message "migration must use a dedicated owner database URL"
Assert-Contains -Text $compose -Pattern 'MOSAIC_WORKER_DATABASE_URL' -Message "workers must use a dedicated BYPASSRLS database URL"
Assert-Contains -Text $compose -Pattern 'MOSAIC_SESSION_TOKEN_PEPPER' -Message "runtime services must receive the session token pepper"
Assert-Contains -Text $compose -Pattern 'MOSAIC_LIVE_EVIDENCE_HMAC_KEY' -Message "catalog activation must receive the live-evidence HMAC key"
Assert-Contains -Text $compose -Pattern '001-runtime-roles\.sh' -Message "PostgreSQL runtime roles must be initialized explicitly"
$roleInit = Get-Content -LiteralPath (Resolve-RepoPath "infra/postgres/init/001-runtime-roles.sh") -Raw
Assert-Contains -Text $roleInit -Pattern 'NOBYPASSRLS' -Message "API role must explicitly disable BYPASSRLS"
Assert-Contains -Text $roleInit -Pattern 'BYPASSRLS' -Message "worker role must explicitly declare BYPASSRLS"
$stagingEnv = Get-Content -LiteralPath (Resolve-RepoPath "infra/compose/staging.env.example") -Raw
Assert-Contains -Text $stagingEnv -Pattern '(?m)^MOSAIC_APP_ENVIRONMENT=staging\s*$' -Message "bundled topology must use the staging environment"
Assert-Contains -Text $stagingEnv -Pattern '(?m)^MOSAIC_SESSION_TOKEN_PEPPER=.+' -Message "staging env must declare the session token pepper"
Assert-Contains -Text $stagingEnv -Pattern '(?m)^MOSAIC_RABBITMQ_URL=amqp://' -Message "staging topology must use the bundled RabbitMQ endpoint"
Assert-Contains -Text $stagingEnv -Pattern '(?m)^MOSAIC_ARTIFACT_STORAGE_S3_ENDPOINT_URL=http://' -Message "staging topology must use the bundled MinIO endpoint"
$productionEnv = Get-Content -LiteralPath (Resolve-RepoPath "infra/compose/production.env.example") -Raw
Assert-Contains -Text $productionEnv -Pattern '(?m)^MOSAIC_APP_ENVIRONMENT=production\s*$' -Message "production env example must remain strict production"
Assert-Contains -Text $productionEnv -Pattern '(?m)^MOSAIC_SESSION_TOKEN_PEPPER=.+' -Message "production env must declare the session token pepper"
Assert-Contains -Text $productionEnv -Pattern '(?m)^MOSAIC_REDIS_URL=rediss://' -Message "production Redis endpoint must use TLS"
Assert-Contains -Text $productionEnv -Pattern '(?m)^MOSAIC_RABBITMQ_URL=amqps://' -Message "production RabbitMQ endpoint must use TLS"
Assert-Contains -Text $productionEnv -Pattern '(?m)^MOSAIC_ARTIFACT_STORAGE_S3_ENDPOINT_URL=https://' -Message "production S3 endpoint must use TLS"
$workflow = Get-Content -LiteralPath (Resolve-RepoPath ".github/workflows/production-release.yml") -Raw
foreach ($service in @("postgres", "redis", "rabbitmq")) {
    Assert-Contains -Text $workflow -Pattern ("(?m)^\s+" + [regex]::Escape($service) + ":\s*$") -Message "CI workflow is missing service $service"
}
Assert-Contains -Text $workflow -Pattern 'name: Start MinIO service' -Message "CI workflow must start MinIO explicitly"
Assert-Contains -Text $workflow -Pattern 'docker run' -Message "CI workflow must use an explicit MinIO server container"
Assert-Contains -Text $workflow -Pattern 'minio/minio:RELEASE' -Message "CI workflow must pin the MinIO image"
Assert-Contains -Text $workflow -Pattern 'server /data --console-address :9001' -Message "CI workflow must pass the MinIO server command"
Assert-Contains -Text $workflow -Pattern '127\.0\.0\.1:9000/minio/health/live' -Message "CI workflow must probe MinIO externally"
Assert-Contains -Text $workflow -Pattern 'postgres_concurrency_gate\.py' -Message "CI workflow must run the real PostgreSQL concurrency gate"
Assert-Contains -Text $workflow -Pattern 'name: Assert CI receipt is bounded' -Message "non-live CI must assert a bounded receipt"
$verifySource = Get-Content -LiteralPath (Resolve-RepoPath "scripts/verify-release.ps1") -Raw
Assert-Contains -Text $verifySource -Pattern 'production-web-image-startup' -Message "release verification must start the built Web image"
Assert-Contains -Text $workflow -Pattern 'RUN_LIVE_PROVIDER_TESTS:\s*"0"' -Message "CI workflow must not enable paid Provider tests"
if ($workflow -match 'provider_smoke\.py\s+--live') {
    throw "CI release workflow must not invoke paid Provider smoke"
}

$selectedConfigPath = Resolve-RepoPath $ConfigPath
if (-not (Test-Path -LiteralPath $selectedConfigPath -PathType Leaf)) {
    throw "release config does not exist: $ConfigPath"
}
if ($RequireConfigHmac) {
    $selectedConfig = Get-Content -LiteralPath $selectedConfigPath -Raw
    if ($selectedConfig -match '(?m)^[A-Za-z][A-Za-z0-9_]*=.*REPLACE_WITH') {
        throw "full release config contains unresolved REPLACE_WITH placeholders"
    }
}

$psScripts = @(
    "scripts/verify-release.ps1",
    "scripts/new-release-receipt.ps1",
    "scripts/verify-release-receipt.ps1",
    "scripts/ops-common.ps1",
    "scripts/backup-postgres.ps1",
    "scripts/restore-postgres.ps1",
    "scripts/mirror-minio.ps1",
    "scripts/restore-minio.ps1",
    "scripts/verify-restore.ps1"
)
foreach ($scriptPath in $psScripts) {
    Assert-PowerShellSyntax -Path (Resolve-RepoPath $scriptPath)
}
if (Test-NativeAvailable -Name "python") {
    Invoke-Required -Name "Python operations syntax" -FilePath "python" -Arguments @(
        "-m", "py_compile", "apps/api/scripts/postgres_concurrency_gate.py", "apps/api/scripts/ensure_artifact_bucket.py", "apps/api/scripts/verify_live_evidence.py"
    ) | Out-Null
} else {
    Add-Limitation "NOT_RUN_ENVIRONMENT: python is unavailable, so operations Python syntax was not executed"
}
$testEvidence.Add([ordered]@{
    name = "release-static-contracts"
    status = "PASS"
    details = "Dockerfiles, production compose service set, local staging boundary, Python/PowerShell syntax, and Next standalone contract"
})

$baselineCheck = Invoke-Required -Name "git rev-parse baseline" -FilePath "git" -Arguments @("rev-parse", "--verify", "$BaselineCommit^{commit}")
$currentCommit = (Invoke-Required -Name "git rev-parse HEAD" -FilePath "git" -Arguments @("rev-parse", "HEAD")).output.Trim()
$ancestorCheck = Invoke-Required -Name "git merge-base baseline" -FilePath "git" -Arguments @("merge-base", "--is-ancestor", $BaselineCommit, $currentCommit)
$diffCheck = Invoke-Required -Name "git diff --check" -FilePath "git" -Arguments @("diff", "--check")
$statusCheck = Invoke-Required -Name "git status" -FilePath "git" -Arguments @("status", "--short", "--branch", "--untracked-files=all")
$dirtyLines = @(
    $statusCheck.output -split "`r?`n" |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and $_ -notmatch '^##(?:\s|$)' }
)
if ($dirtyLines.Count -gt 0 -and -not $AllowDirty) {
    throw "worktree is not clean; commit the release before generating an acceptance receipt"
}
if ($dirtyLines.Count -gt 0) {
    Add-Limitation "WORKTREE_DIRTY_ALLOWED: static evidence was generated with -AllowDirty and is not a release acceptance"
}

if (-not [string]::IsNullOrWhiteSpace($ProviderEvidencePath)) {
    if (-not (Test-NativeAvailable -Name "uv")) {
        throw "uv is required to verify signed Provider evidence"
    }
    $providerEvidence = Resolve-RepoPath $ProviderEvidencePath
    $providerResult = Invoke-Required -Name "signed Provider live evidence" -FilePath "uv" -Arguments @(
        "run", "--project", "apps/api", "python", "apps/api/scripts/verify_live_evidence.py", $providerEvidence
    )
    $providerPayload = $providerResult.output | ConvertFrom-Json
    if (
        [string]$providerPayload.status -ne "ok" -or
        [string]$providerPayload.source_commit -ne $currentCommit -or
        @($providerPayload.modalities).Count -ne 4
    ) {
        throw "signed Provider evidence summary is incomplete"
    }
    $testEvidence.Add([ordered]@{
        name = "provider-live-evidence"
        status = "PASS"
        source_commit = [string]$providerPayload.source_commit
        evidence_sha256 = [string]$providerPayload.evidence_sha256
        output_sha256 = $providerResult.output_sha256
    })
} else {
    if ($RequireProviderEvidence) {
        throw "-ProviderEvidencePath is required for full release acceptance"
    }
    Add-Limitation "NOT_RUN: current-commit signed Provider live evidence was not supplied"
}

$migrationHead = $null
if (Test-NativeAvailable -Name "uv") {
    $migrationResult = Invoke-Required -Name "alembic heads" -FilePath "uv" -Arguments @(
        "run", "--project", "apps/api", "alembic", "-c", "apps/api/alembic.ini", "heads"
    )
    $heads = @(
        $migrationResult.output -split "`r?`n" |
            Where-Object { $_ -match '^\s*([A-Za-z0-9_.-]+)\s+\(head\)\s*$' } |
            ForEach-Object { ([regex]::Match($_, '^\s*([A-Za-z0-9_.-]+)\s+\(head\)\s*$')).Groups[1].Value }
    )
    if ($heads.Count -ne 1) {
        throw "migration head check expected exactly one head"
    }
    $migrationHead = $heads[0]
    if (-not [string]::IsNullOrWhiteSpace($ExpectedMigrationHead) -and $migrationHead -ne $ExpectedMigrationHead) {
        throw "migration head $migrationHead does not match expected head $ExpectedMigrationHead"
    }
    $testEvidence.Add([ordered]@{
        name = "migration-head"
        status = "PASS"
        head = $migrationHead
    })
} else {
    Add-Limitation "NOT_RUN_ENVIRONMENT: uv is unavailable, so Alembic head was not executed"
}

$dockerAvailable = Test-NativeAvailable -Name "docker"
$imageDigestPath = $null
if (($BuildImages -or $RequireImageDigests) -and $StaticOnly) {
    throw "image verification requires a non-static run"
}
if ($dockerAvailable -and -not $StaticOnly) {
    $composePath = Resolve-RepoPath "infra/compose/docker-compose.production.yml"
    $configPath = Resolve-RepoPath $ConfigPath
    Invoke-Required -Name "docker compose config" -FilePath "docker" -Arguments @(
        "compose", "--env-file", $configPath, "-f", $composePath, "config", "--quiet"
    ) | Out-Null
    $testEvidence.Add([ordered]@{
        name = "production-compose-config"
        status = "PASS"
    })
    if ($BuildImages -or $RequireImageDigests) {
        $composeConfig = Invoke-Required -Name "docker compose config json" -FilePath "docker" -Arguments @(
            "compose", "--env-file", $configPath, "-f", $composePath, "config", "--format", "json"
        )
        $composeModel = $composeConfig.output | ConvertFrom-Json
        $apiImage = [string]$composeModel.services.api.image
        $webImage = [string]$composeModel.services.web.image
        if ([string]::IsNullOrWhiteSpace($apiImage) -or [string]::IsNullOrWhiteSpace($webImage)) {
            throw "production compose must resolve API and Web image references"
        }
        if ($BuildImages) {
            Invoke-Required -Name "docker compose build" -FilePath "docker" -Arguments @(
                "compose", "--env-file", $configPath, "-f", $composePath, "build"
            ) | Out-Null
        }
        $serviceImageRefs = [ordered]@{
            web = $webImage
            api = $apiImage
            "chat-relay" = $apiImage
            "generation-relay" = $apiImage
            "chat-worker" = $apiImage
            "image-audio-worker" = $apiImage
            "video-worker" = $apiImage
            "artifact-cleanup" = $apiImage
        }
        $digestByImage = @{}
        $imageDigests = [ordered]@{}
        $imageRefs = [ordered]@{}
        foreach ($service in $serviceImageRefs.Keys) {
            $imageRef = [string]$serviceImageRefs[$service]
            $imageRefs[$service] = $imageRef
            if (-not $digestByImage.ContainsKey($imageRef)) {
                $inspect = Invoke-Required -Name ("docker image inspect " + $imageRef) -FilePath "docker" -Arguments @(
                    "image", "inspect", "--format", "{{.Id}}", $imageRef
                )
                $digestLines = @(
                    $inspect.output -split "`r?`n" |
                        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                        ForEach-Object { $_.Trim() }
                )
                if ($digestLines.Count -ne 1 -or $digestLines[0] -notmatch '^sha256:[0-9a-f]{64}$') {
                    throw "docker image inspect did not return an immutable digest for $imageRef"
                }
                $digestByImage[$imageRef] = $digestLines[0]
            }
            $imageDigests[$service] = $digestByImage[$imageRef]
        }
        $imageDigestPath = Resolve-RepoPath "output/release/.image-digests.json"
        $imageManifest = [ordered]@{
            schema_version = 1
            generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            commit = $currentCommit
            image_refs = $imageRefs
            image_digests = $imageDigests
        }
        $imageManifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $imageDigestPath -Encoding utf8
        $testEvidence.Add([ordered]@{
            name = "production-image-digests"
            status = "PASS"
            details = "Web, API, relays, workers, and artifact cleanup resolve to immutable local image digests"
        })

        $webContainerId = $null
        try {
            $runtimeUser = Invoke-Required -Name "web image non-root user" -FilePath "docker" -Arguments @(
                "image", "inspect", "--format", "{{.Config.User}}", $webImage
            )
            if ($runtimeUser.output.Trim() -ne "mosaic") {
                throw "built Web image must run as mosaic"
            }
            $runWeb = Invoke-Required -Name "start built Web image" -FilePath "docker" -Arguments @(
                "run", "--detach", "--rm", "--publish", "127.0.0.1::3000", $webImage
            )
            $webContainerId = $runWeb.output.Trim()
            if ($webContainerId -notmatch '^[0-9a-f]{12,64}$') {
                throw "docker run did not return a container ID"
            }
            $portResult = Invoke-Required -Name "inspect built Web image port" -FilePath "docker" -Arguments @(
                "port", $webContainerId, "3000/tcp"
            )
            $portMatch = [regex]::Match($portResult.output, '(?:127\.0\.0\.1|0\.0\.0\.0):(\d+)')
            if (-not $portMatch.Success) {
                throw "built Web image did not publish its HTTP port"
            }
            $webPort = [int]$portMatch.Groups[1].Value
            $webReady = $false
            for ($attempt = 1; $attempt -le 60; $attempt++) {
                try {
                    $rootResponse = Invoke-WebRequest -Uri "http://127.0.0.1:$webPort/" -UseBasicParsing -TimeoutSec 3
                    $loginResponse = Invoke-WebRequest -Uri "http://127.0.0.1:$webPort/login" -UseBasicParsing -TimeoutSec 3
                    if ($rootResponse.StatusCode -eq 200 -and $loginResponse.StatusCode -eq 200) {
                        $webReady = $true
                        break
                    }
                } catch {
                    # The bounded retry loop owns transient startup failures.
                }
                Start-Sleep -Seconds 1
            }
            if (-not $webReady) {
                Invoke-Required -Name "built Web image logs" -FilePath "docker" -Arguments @(
                    "logs", $webContainerId
                ) | Out-Null
                throw "built Web image did not become HTTP ready"
            }
            $testEvidence.Add([ordered]@{
                name = "production-web-image-startup"
                status = "PASS"
                runtime_user = "mosaic"
                root_status = 200
                login_status = 200
            })
        } finally {
            if (-not [string]::IsNullOrWhiteSpace($webContainerId)) {
                & docker rm --force $webContainerId 2>&1 | Out-Null
            }
        }
    }
} else {
    if ($BuildImages -or $RequireImageDigests) {
        throw "Docker is unavailable; required image verification cannot run"
    }
    Add-Limitation "NOT_RUN_ENVIRONMENT: Docker is unavailable or -StaticOnly was selected; compose was not rendered"
}

if ($RunTests -and -not $StaticOnly) {
    $webCommands = @(
        @{ name = "web lint"; arguments = @("lint:web") },
        @{ name = "web typecheck"; arguments = @("typecheck:web") },
        @{ name = "web boundaries"; arguments = @("check:web-boundaries") },
        @{ name = "workspace package tests"; arguments = @("test:packages") },
        @{ name = "web Vitest"; arguments = @("test:web") },
        @{ name = "web standalone build"; arguments = @("build:web") }
    )
    foreach ($webCommand in $webCommands) {
        $webResult = Invoke-Required -Name ("pnpm " + $webCommand.name) -FilePath "pnpm" -Arguments $webCommand.arguments
        $testEvidence.Add([ordered]@{
            name = $webCommand.name
            status = "PASS"
            exit_code = $webResult.exit_code
            output_sha256 = $webResult.output_sha256
        })
    }
    $apiTests = Invoke-Required -Name "pnpm verify:api" -FilePath "pnpm" -Arguments @("verify:api")
    $testEvidence.Add([ordered]@{
        name = "pnpm verify:api"
        status = "PASS"
        exit_code = $apiTests.exit_code
        output_sha256 = $apiTests.output_sha256
    })
    if ($env:MOSAIC_RELEASE_RUN_CONCURRENCY_GATE -eq "1") {
        $concurrencyGate = Invoke-Required -Name "PostgreSQL concurrency gate" -FilePath "uv" -Arguments @(
            "run", "--project", "apps/api", "python", "apps/api/scripts/postgres_concurrency_gate.py"
        )
        $testEvidence.Add([ordered]@{
            name = "postgres-row-lock"
            status = "PASS"
            exit_code = $concurrencyGate.exit_code
            output_sha256 = $concurrencyGate.output_sha256
        })
    } else {
        Add-Limitation "NOT_RUN_ENVIRONMENT: MOSAIC_RELEASE_RUN_CONCURRENCY_GATE is not 1; real PostgreSQL concurrency gate was not executed"
    }
} elseif ($RunTests) {
    Add-Limitation "NOT_RUN_ENVIRONMENT: -StaticOnly suppresses runtime test commands"
} else {
    Add-Limitation "NOT_RUN: -RunTests was not selected"
}

$evidencePath = Resolve-RepoPath "output/release/.verify-evidence.json"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $evidencePath) | Out-Null
$evidence = [ordered]@{
    commands = @($commandEvidence)
    tests = @($testEvidence)
    limitations = @($limitations)
}
$evidence | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $evidencePath -Encoding utf8

try {
    $powershellCommand = (Get-Process -Id $PID -ErrorAction Stop).Path
    if ([string]::IsNullOrWhiteSpace($powershellCommand)) {
        throw "unable to resolve the current PowerShell executable"
    }
    $receiptArguments = @(
        "-NoProfile", "-NonInteractive", "-File", (Resolve-RepoPath "scripts/new-release-receipt.ps1"),
        "-RepoRoot", $RepoRoot, "-OutputPath", $ReceiptPath, "-EvidencePath", $evidencePath,
        "-BaselineCommit", $BaselineCommit
    )
    if (-not [string]::IsNullOrWhiteSpace($migrationHead)) {
        $receiptArguments += @("-MigrationHead", $migrationHead)
    }
    $receiptArguments += @("-ConfigPath", $ConfigPath)
    if ($RequireConfigHmac) { $receiptArguments += "-RequireConfigHmac" }
    if ($null -ne $imageDigestPath) {
        $receiptArguments += @("-ImageDigestPath", $imageDigestPath)
    }
    if ($RequireImageDigests) { $receiptArguments += "-RequireImageDigests" }
    if (-not [string]::IsNullOrWhiteSpace($ProviderEvidencePath)) {
        $receiptArguments += @("-ProviderEvidencePath", $ProviderEvidencePath)
    }
    if ($RequireProviderEvidence) { $receiptArguments += "-RequireProviderEvidence" }
    Invoke-Required -Name "new-release-receipt.ps1" -FilePath $powershellCommand -Arguments $receiptArguments | Out-Null
} finally {
    if (Test-Path -LiteralPath $evidencePath -PathType Leaf) {
        Remove-Item -LiteralPath $evidencePath -Force
    }
}

$receiptFullPath = Resolve-RepoPath $ReceiptPath
if (-not (Test-Path -LiteralPath $receiptFullPath -PathType Leaf)) {
    throw "release receipt was not generated"
}
$finalStatus = Invoke-Required -Name "git status after receipt" -FilePath "git" -Arguments @("status", "--short", "--branch", "--untracked-files=all")
$finalDirtyLines = @(
    $finalStatus.output -split "`r?`n" |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and $_ -notmatch '^##(?:\s|$)' }
)
if ($finalDirtyLines.Count -gt 0 -and -not $AllowDirty) {
    throw "worktree changed while generating the receipt"
}

$receipt = Get-Content -LiteralPath $receiptFullPath -Raw | ConvertFrom-Json
$fullAcceptanceRequested = (
    $RunTests -and $RequireConfigHmac -and $RequireImageDigests -and $RequireProviderEvidence
)
if ($fullAcceptanceRequested -and [string]$receipt.acceptance_status -ne "PASS") {
    throw "full release acceptance was requested but the receipt is not PASS"
}

if ($AllowDirty -and $finalDirtyLines.Count -gt 0) {
    Write-Output ("PASS static verification (dirty tree explicitly allowed); receipt: " + $ReceiptPath)
} elseif ([string]$receipt.acceptance_status -ne "PASS") {
    Write-Output ("PASS bounded verification (not release acceptance); receipt: " + $ReceiptPath)
} else {
    Write-Output ("PASS release verification; receipt: " + $ReceiptPath)
}
