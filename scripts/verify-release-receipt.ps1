[CmdletBinding()]
param(
    [string]$ReceiptPath = "output/release/receipt.json"
)

$ErrorActionPreference = "Stop"

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

$resolved = [IO.Path]::GetFullPath($ReceiptPath)
if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
    throw "release receipt does not exist"
}

$receipt = Get-Content -LiteralPath $resolved -Raw | ConvertFrom-Json -AsHashtable
if (
    $receipt.schema_version -ne 1 -or
    [string]$receipt.receipt_hmac_schema -ne "mosaic_release_receipt_v1" -or
    [string]$receipt.receipt_hmac_status -ne "PASS" -or
    [string]$receipt.receipt_hmac_sha256 -notmatch '^[0-9a-f]{64}$'
) {
    throw "release receipt HMAC fields are invalid"
}

$expectedHex = [string]$receipt.receipt_hmac_sha256
$receipt.Remove("receipt_hmac_status")
$receipt.Remove("receipt_hmac_sha256")
$key = [Environment]::GetEnvironmentVariable("MOSAIC_RELEASE_HMAC_KEY")
if (
    [string]::IsNullOrWhiteSpace($key) -or
    $key.Length -lt 32 -or
    $key -match '(?i)REPLACE_WITH|placeholder'
) {
    throw "a non-placeholder MOSAIC_RELEASE_HMAC_KEY of at least 32 characters is required"
}

$keyBytes = [Text.Encoding]::UTF8.GetBytes($key)
$payload = [Text.Encoding]::UTF8.GetBytes((ConvertTo-CanonicalJson $receipt))
$hmac = [Security.Cryptography.HMACSHA256]::new($keyBytes)
try {
    $actual = $hmac.ComputeHash($payload)
    $expected = [Convert]::FromHexString($expectedHex)
    if (-not [Security.Cryptography.CryptographicOperations]::FixedTimeEquals($actual, $expected)) {
        throw "release receipt HMAC does not match"
    }
} finally {
    $hmac.Dispose()
    [Array]::Clear($keyBytes, 0, $keyBytes.Length)
    [Array]::Clear($payload, 0, $payload.Length)
}

Write-Output "release receipt integrity: ok"
