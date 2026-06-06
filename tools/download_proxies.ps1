# Downloads the three external proxy executables used by the VPN client.
# Always pulls the LATEST published release by querying the GitHub Releases API.
#
#   - opera-proxy    (Alexey71/opera-proxy)
#   - warp-awg-gen   (Skiro1/warp-awg-gen)
#   - hola-proxy     (snawoot-proxies-forks/hola-proxy)
#
# Idempotent: by default skips files that already exist.
# Use -Force to redownload and replace existing .exe files.

[CmdletBinding()]
param(
    [switch]$Force = $false,
    [string]$ProjectRoot
)

if (-not $ProjectRoot) {
    if ($PSScriptRoot) {
        $ProjectRoot = (Split-Path -Parent $PSScriptRoot)
    } else {
        $ProjectRoot = (Get-Location).Path
    }
}

$ErrorActionPreference = "Stop"
$ProgressPreference   = "SilentlyContinue"

function Log($msg, $color = "White") {
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] $msg" -ForegroundColor $color
}

function Get-LatestAsset {
    <#
    .SYNOPSIS
        Returns the latest published release asset matching a predicate.
    .PARAMETER Repo
        "owner/repo" string.
    .PARAMETER AssetMatch
        Regex applied to asset name.
    #>
    param(
        [Parameter(Mandatory)] [string]$Repo,
        [Parameter(Mandatory)] [string]$AssetMatch
    )
    $api = "https://api.github.com/repos/$Repo/releases/latest"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $headers = @{
            "User-Agent" = "vpn-client-proxy-downloader"
            "Accept"     = "application/vnd.github+json"
        }
        $release = Invoke-RestMethod -Uri $api -Headers $headers -TimeoutSec 30
    } catch {
        Log "    GitHub API request failed for $Repo`: $_" "Red"
        return $null
    }
    if (-not $release -or -not $release.tag_name) {
        Log "    No release found for $Repo" "Yellow"
        return $null
    }
    $asset = $release.assets | Where-Object { $_.name -match $AssetMatch } | Select-Object -First 1
    if (-not $asset) {
        Log "    No asset matching /$AssetMatch/ in $($release.tag_name) for $Repo" "Yellow"
        return $null
    }
    return [PSCustomObject]@{
        TagName   = $release.tag_name
        AssetName = $asset.name
        AssetUrl  = $asset.browser_download_url
    }
}

function Download {
    param(
        [string]$Url,
        [string]$OutFile,
        [string]$Description
    )
    $outDir = Split-Path -Parent $OutFile
    if (!(Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
    if ((Test-Path $OutFile) -and -not $Force) {
        Log "  - already present: $Description" "DarkGray"
        return
    }
    Log "  - downloading: $Description" "Cyan"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $tmp = [System.IO.Path]::GetTempFileName()
        Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing -TimeoutSec 120
        Move-Item -LiteralPath $tmp -Destination $OutFile -Force
        Log "    saved -> $OutFile" "DarkGray"
    } catch {
        Log "    FAILED: $_" "Red"
        if (Test-Path $OutFile) { Remove-Item $OutFile -Force }
    }
}

# Each proxy has its own source repo, latest tag and asset pattern.
$proxies = @(
    @{
        Name        = "opera-proxy"
        OutFile     = (Join-Path $ProjectRoot "opera-proxy.exe")
        Repo        = "Alexey71/opera-proxy"
        AssetMatch  = "windows-amd64\.exe$"
    },
    @{
        Name        = "warp-awg-gen"
        OutFile     = (Join-Path $ProjectRoot "warp-awg-gen.exe")
        Repo        = "Skiro1/warp-awg-gen"
        AssetMatch  = "windows-amd64\.exe$"
    },
    @{
        Name        = "hola-proxy"
        OutFile     = (Join-Path $ProjectRoot "hola-proxy.exe")
        Repo        = "snawoot-proxies-forks/hola-proxy"
        AssetMatch  = "windows-amd64\.exe$"
    }
)

foreach ($p in $proxies) {
    Log "[$($p.Name)] querying latest release from $($p.Repo)..." "Yellow"
    $rel = Get-LatestAsset -Repo $p.Repo -AssetMatch $p.AssetMatch
    if ($rel) {
        Log "  latest: $($rel.TagName) - $($rel.AssetName)" "Cyan"
        Download -Url $rel.AssetUrl -OutFile $p.OutFile -Description $rel.AssetName
    } else {
        Log "  Could not determine latest $($p.Name) release" "Red"
    }
}

Log "" "White"
Log "============================================" "Cyan"
Log "Proxy setup complete." "Green"
Log "============================================" "Cyan"
