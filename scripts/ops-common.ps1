function Get-RequiredSetting {
    param(
        [string]$Value,
        [Parameter(Mandatory = $true)][string]$EnvironmentName
    )

    $resolved = if ([string]::IsNullOrWhiteSpace($Value)) {
        [Environment]::GetEnvironmentVariable($EnvironmentName)
    } else {
        $Value
    }
    if ([string]::IsNullOrWhiteSpace($resolved)) {
        throw "$EnvironmentName is required"
    }
    return $resolved
}

function Resolve-AbsolutePath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [IO.Path]::GetFullPath($Path)
}

function Assert-SafeDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    $resolved = Resolve-AbsolutePath $Path
    $root = [IO.Path]::GetPathRoot($resolved)
    if ($resolved.TrimEnd("\", "/") -eq $root.TrimEnd("\", "/")) {
        throw "refusing to use a filesystem root as a backup target"
    }
    $repo = (Resolve-AbsolutePath $RepoRoot).TrimEnd("\", "/")
    if ($resolved.TrimEnd("\", "/") -eq $repo) {
        throw "refusing to use the repository root as a backup target"
    }
    New-Item -ItemType Directory -Force -Path $resolved | Out-Null
    return $resolved
}

function Assert-SafeInputFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    $resolved = Resolve-AbsolutePath $Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "input file does not exist"
    }
    return $resolved
}

function Test-DirectoryEmpty {
    param([Parameter(Mandatory = $true)][string]$Path)
    return $null -eq (Get-ChildItem -LiteralPath $Path -Force | Select-Object -First 1)
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
        output_sha256 = [Convert]::ToHexString(
            [Security.Cryptography.SHA256]::HashData(
                [Text.Encoding]::UTF8.GetBytes($output)
            )
        ).ToLowerInvariant()
        output_line_count = if ([string]::IsNullOrEmpty($output)) { 0 } else { ($output -split "`r?`n").Count }
        output = $output
    }
}

function Set-ChildSecret {
    param(
        [Parameter(Mandatory = $true)][string]$EnvironmentName,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $old = [Environment]::GetEnvironmentVariable($EnvironmentName, "Process")
    Set-Item -LiteralPath ("Env:" + $EnvironmentName) -Value $Value
    return $old
}

function Restore-ChildSecret {
    param(
        [Parameter(Mandatory = $true)][string]$EnvironmentName,
        [AllowNull()][string]$OldValue
    )

    if ($null -eq $OldValue) {
        Remove-Item -LiteralPath ("Env:" + $EnvironmentName) -ErrorAction SilentlyContinue
    } else {
        Set-Item -LiteralPath ("Env:" + $EnvironmentName) -Value $OldValue
    }
}

function Write-SafeJson {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $Value | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Path -Encoding utf8
}

function Get-FileDigest {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-McHostValue {
    param(
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [Parameter(Mandatory = $true)][string]$AccessKey,
        [Parameter(Mandatory = $true)][string]$SecretKey
    )

    $uri = [Uri]$Endpoint
    if ($uri.Scheme -notin @("http", "https") -or [string]::IsNullOrWhiteSpace($uri.Host) -or $uri.AbsolutePath -ne "/") {
        throw "MinIO endpoint must be a bare HTTP(S) URL"
    }
    $escapedAccessKey = [Uri]::EscapeDataString($AccessKey)
    $escapedSecretKey = [Uri]::EscapeDataString($SecretKey)
    return ("{0}://{1}:{2}@{3}" -f $uri.Scheme, $escapedAccessKey, $escapedSecretKey, $uri.Authority)
}

function Set-McHostEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$Alias,
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [Parameter(Mandatory = $true)][string]$AccessKey,
        [Parameter(Mandatory = $true)][string]$SecretKey
    )

    $name = "MC_HOST_$Alias"
    $oldValue = [Environment]::GetEnvironmentVariable($name, "Process")
    Set-Item -LiteralPath ("Env:" + $name) -Value (Get-McHostValue -Endpoint $Endpoint -AccessKey $AccessKey -SecretKey $SecretKey)
    return [ordered]@{ name = $name; old_value = $oldValue }
}

function Restore-McHostEnvironment {
    param([Parameter(Mandatory = $true)][System.Collections.IDictionary]$State)

    if ($null -eq $State.old_value) {
        Remove-Item -LiteralPath ("Env:" + $State.name) -ErrorAction SilentlyContinue
    } else {
        Set-Item -LiteralPath ("Env:" + $State.name) -Value $State.old_value
    }
}
