# Downloads everything needed for zapret/zapret2 binaries, lists, and lua scripts.
# Always pulls the LATEST published release by querying the GitHub Releases API.
#
# Sources:
#   - bol-van/zapret                -> v1 binaries (winws.exe, .bin fakes, helpers)
#   - bol-van/zapret2               -> v2 binaries (winws2.exe, .bin fakes, helpers)
#   - bol-van/zapret-win-bundle     -> lua scripts (zapret-lib, antidpi, auto, obfs, ...)
#   - Flowseal/zapret-discord-youtube -> v1 lists (ipset, hostlist, ...)
#   - youtubediscord/zapret         -> custom lua scripts (not publicly distributed)
#
# Idempotent: by default skips files that already exist.
# Use -Force to wipe the cache directory and redownload everything from scratch.
# Use -Update to also remove already-deployed binary files (zapret/bin, zapret/zapret2/bin)
# before re-copying - this guarantees the latest published binaries are in place.

[CmdletBinding()]
param(
    [switch]$Force = $false,
    [switch]$Update = $false,
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

# Persistent cache directory for downloaded zip archives (speeds up re-runs).
$tempDir = Join-Path $env:TEMP "vpn_client_zapret_cache"
if (!(Test-Path $tempDir)) { New-Item -ItemType Directory -Path $tempDir -Force | Out-Null }

function Log($msg, $color = "White") {
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] $msg" -ForegroundColor $color
}

function Get-LatestRelease {
    <#
    .SYNOPSIS
        Queries the GitHub Releases API for the latest release of a repo and
        picks the asset whose name matches a predicate.
    .PARAMETER Repo
        "owner/repo" string, e.g. "bol-van/zapret".
    .PARAMETER AssetNameMatch
        Optional regex; if supplied, the first asset whose name matches is
        returned. If omitted, the first asset with a .zip extension is used.
    .OUTPUTS
        PSCustomObject with TagName, AssetName, AssetUrl, Size.
    #>
    param(
        [Parameter(Mandatory)] [string]$Repo,
        [string]$AssetNameMatch
    )
    $api = "https://api.github.com/repos/$Repo/releases/latest"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $headers = @{
            "User-Agent" = "vpn-client-zapret-downloader"
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
    $asset = $null
    if ($AssetNameMatch) {
        $asset = $release.assets | Where-Object { $_.name -match $AssetNameMatch } | Select-Object -First 1
    } else {
        $asset = $release.assets | Where-Object { $_.name -like "*.zip" } | Select-Object -First 1
    }
    if (-not $asset) {
        Log "    No matching asset in $($release.tag_name) for $Repo" "Yellow"
        return $null
    }
    return [PSCustomObject]@{
        TagName   = $release.tag_name
        AssetName = $asset.name
        AssetUrl  = $asset.browser_download_url
        Size      = $asset.size
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

function ExtractZip {
    param(
        [string]$ZipPath,
        [string]$DestDir,
        [string]$Description
    )
    if (!(Test-Path $DestDir)) { New-Item -ItemType Directory -Path $DestDir -Force | Out-Null }
    Log "  - extracting: $Description" "Cyan"
    try {
        Expand-Archive -LiteralPath $ZipPath -DestinationPath $DestDir -Force
    } catch {
        Log "    FAILED: $_" "Red"
    }
}

function CopyFrom {
    param(
        [string]$Source,
        [string]$Dest,
        [string]$Pattern = "*",
        [string]$Description
    )
    if (!(Test-Path $Source)) {
        Log "    source not found: $Source" "Yellow"
        return
    }
    if (!(Test-Path $Dest)) { New-Item -ItemType Directory -Path $Dest -Force | Out-Null }
    # Stage matching items into a temp directory, then move them into Dest
    # using cmd `move /Y` which can replace files that are open with
    # FILE_SHARE_DELETE. This is needed because WinDivert64.sys is held by
    # a running winws.exe while the user is connected.
    $tmp = Join-Path $env:TEMP ("copyfrom_" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    try {
        $sourceItems = @(Get-ChildItem -Path $Source -Filter $Pattern -ErrorAction SilentlyContinue)
        if ($sourceItems.Count -eq 0) {
            Log "    no matches: $Pattern in $Source" "Yellow"
            return
        }
        foreach ($it in $sourceItems) {
            $target = Join-Path $tmp $it.Name
            if ($it.PSIsContainer) {
                New-Item -ItemType Directory -Path $target -Force | Out-Null
                Copy-Item -Path (Join-Path $it.FullName "*") -Destination $target -Recurse -Force
            } else {
                Copy-Item -LiteralPath $it.FullName -Destination $target -Force
            }
        }
        $staged = Get-ChildItem -Path $tmp
        foreach ($it in $staged) {
            $final = Join-Path $Dest $it.Name
            if ($it.PSIsContainer) {
                if (Test-Path $final) { Remove-Item -LiteralPath $final -Recurse -Force -ErrorAction SilentlyContinue }
                Move-Item -LiteralPath $it.FullName -Destination $Dest -Force
            } else {
                $ok = $false
                try {
                    & cmd.exe /c "move /Y `"$($it.FullName)`" `"$final`"" | Out-Null
                    $ok = $true
                } catch { $ok = $false }
                if (-not $ok) {
                    try { Copy-Item -LiteralPath $it.FullName -Destination $final -Force } catch {}
                }
            }
        }
        Log "  - copied: $Description" "Green"
    } catch {
        Log "    copy failed for $Description`: $_" "Yellow"
    } finally {
        if (Test-Path $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

# ----------------------------------------------------------------------
# 1. bol-van/zapret - v1 binaries + .bin fakes (LATEST release)
# ----------------------------------------------------------------------
Log "[1/5] bol-van/zapret (v1) - querying latest release..." "Yellow"
$rel = Get-LatestRelease -Repo "bol-van/zapret"
if ($rel) {
    Log "  latest: $($rel.TagName) - $($rel.AssetName)" "Cyan"
    $v1TagSafe = $rel.TagName.TrimStart('v')
    $v1Zip = Join-Path $tempDir "zapret-$($rel.TagName).zip"
    $v1Extract = Join-Path $tempDir "zapret-$($rel.TagName)"
    $v1BinDst = Join-Path $ProjectRoot "zapret\bin"
    $v1ListsDst = Join-Path $ProjectRoot "zapret\lists"

    Download -Url $rel.AssetUrl -OutFile $v1Zip -Description $rel.AssetName

    if (Test-Path $v1Zip) {
        ExtractZip -ZipPath $v1Zip -DestDir $tempDir -Description $rel.AssetName
        $v1Win = Join-Path $v1Extract "binaries\windows-x86_64"
        if (Test-Path $v1Win) {
            CopyFrom -Source $v1Win -Dest $v1BinDst -Pattern "winws.exe" -Description "winws.exe (v1)"
            CopyFrom -Source $v1Win -Dest $v1BinDst -Pattern "cygwin1.dll" -Description "cygwin1.dll"
            CopyFrom -Source $v1Win -Dest $v1BinDst -Pattern "WinDivert.dll" -Description "WinDivert.dll"
            CopyFrom -Source $v1Win -Dest $v1BinDst -Pattern "WinDivert64.sys" -Description "WinDivert64.sys"
            CopyFrom -Source $v1Win -Dest $v1BinDst -Pattern "ip2net.exe" -Description "ip2net.exe"
            CopyFrom -Source $v1Win -Dest $v1BinDst -Pattern "mdig.exe" -Description "mdig.exe"
            CopyFrom -Source $v1Win -Dest $v1BinDst -Pattern "killall.exe" -Description "killall.exe"
        }
        $v1Fake = Join-Path $v1Extract "files\fake"
        if (Test-Path $v1Fake) {
            CopyFrom -Source $v1Fake -Dest $v1BinDst -Pattern "*.bin" -Description "v1 .bin fakes"
        }
    }
} else {
    Log "  Could not determine latest v1 release" "Red"
}

# ----------------------------------------------------------------------
# 2. bol-van/zapret2 - v2 binaries + .bin fakes (LATEST release)
# ----------------------------------------------------------------------
Log "[2/5] bol-van/zapret2 (v2) - querying latest release..." "Yellow"
$rel2 = Get-LatestRelease -Repo "bol-van/zapret2"
if ($rel2) {
    Log "  latest: $($rel2.TagName) - $($rel2.AssetName)" "Cyan"
    $v2Zip = Join-Path $tempDir "zapret2-$($rel2.TagName).zip"
    $v2Extract = Join-Path $tempDir "zapret2-$($rel2.TagName)"
    $v2BinDst = Join-Path $ProjectRoot "zapret\zapret2\bin"
    $v2ListsDst = Join-Path $ProjectRoot "zapret\zapret2\lists"

    Download -Url $rel2.AssetUrl -OutFile $v2Zip -Description $rel2.AssetName

    if (Test-Path $v2Zip) {
        ExtractZip -ZipPath $v2Zip -DestDir $tempDir -Description $rel2.AssetName
        $v2Win = Join-Path $v2Extract "binaries\windows-x86_64"
        if (Test-Path $v2Win) {
            CopyFrom -Source $v2Win -Dest $v2BinDst -Pattern "winws2.exe" -Description "winws2.exe (v2)"
            CopyFrom -Source $v2Win -Dest $v2BinDst -Pattern "cygwin1.dll" -Description "cygwin1.dll"
            CopyFrom -Source $v2Win -Dest $v2BinDst -Pattern "WinDivert.dll" -Description "WinDivert.dll"
            CopyFrom -Source $v2Win -Dest $v2BinDst -Pattern "WinDivert64.sys" -Description "WinDivert64.sys"
            CopyFrom -Source $v2Win -Dest $v2BinDst -Pattern "ip2net.exe" -Description "ip2net.exe"
            CopyFrom -Source $v2Win -Dest $v2BinDst -Pattern "mdig.exe" -Description "mdig.exe"
            CopyFrom -Source $v2Win -Dest $v2BinDst -Pattern "killall.exe" -Description "killall.exe"
        }
        $v2Fake = Join-Path $v2Extract "files\fake"
        if (Test-Path $v2Fake) {
            CopyFrom -Source $v2Fake -Dest $v2BinDst -Pattern "*.bin" -Description "v2 .bin fakes"
        }
    }
} else {
    Log "  Could not determine latest v2 release" "Red"
}

# ----------------------------------------------------------------------
# 3. bol-van/zapret-win-bundle - lua scripts (master branch, no releases)
# ----------------------------------------------------------------------
Log "[3/5] bol-van/zapret-win-bundle (lua scripts)" "Yellow"
$v1BinDst = Join-Path $ProjectRoot "zapret\bin"
$v2BinDst = Join-Path $ProjectRoot "zapret\zapret2\bin"
$v1ListsDst = Join-Path $ProjectRoot "zapret\lists"
$bundleFiles = @{
    "lua/zapret-lib.lua"      = (Join-Path $v2BinDst "lua\zapret-lib.lua")
    "lua/zapret-antidpi.lua"  = (Join-Path $v2BinDst "lua\zapret-antidpi.lua")
    "lua/zapret-auto.lua"     = (Join-Path $v2BinDst "lua\zapret-auto.lua")
    "lua/zapret-obfs.lua"     = (Join-Path $v2BinDst "lua\zapret-obfs.lua")
    "lua/zapret-pcap.lua"     = (Join-Path $v2BinDst "lua\zapret-pcap.lua")
    "lua/zapret-tests.lua"    = (Join-Path $v2BinDst "lua\zapret-tests.lua")
    "files/list-youtube.txt"  = (Join-Path $v1ListsDst "list-youtube.txt")
}
# Same lua scripts are also placed under zapret/bin/lua for v1 strategies
# that may use @lua references.
$bundleFilesV1 = @{
    "lua/zapret-lib.lua"      = (Join-Path $v1BinDst "lua\zapret-lib.lua")
    "lua/zapret-antidpi.lua"  = (Join-Path $v1BinDst "lua\zapret-antidpi.lua")
    "lua/zapret-auto.lua"     = (Join-Path $v1BinDst "lua\zapret-auto.lua")
    "lua/zapret-obfs.lua"     = (Join-Path $v1BinDst "lua\zapret-obfs.lua")
}
$base = "https://raw.githubusercontent.com/bol-van/zapret-win-bundle/master/zapret-winws"
foreach ($k in $bundleFiles.Keys) {
    $url = "$base/$k"
    $dst = $bundleFiles[$k]
    $desc = "win-bundle/$k"
    if ((Test-Path $dst) -and -not $Force) {
        Log "  - already present: $desc" "DarkGray"
    } else {
        Download -Url $url -OutFile $dst -Description $desc
    }
}
foreach ($k in $bundleFilesV1.Keys) {
    $url = "$base/$k"
    $dst = $bundleFilesV1[$k]
    $desc = "win-bundle/$k -> zapret/bin/lua"
    if ((Test-Path $dst) -and -not $Force) {
        Log "  - already present: $desc" "DarkGray"
    } else {
        Download -Url $url -OutFile $dst -Description $desc
    }
}

# ----------------------------------------------------------------------
# 4. youtubediscord/zapret - custom lua scripts
#    The custom lua scripts (custom_funcs.lua, custom_diag.lua,
#    zapret-multishake.lua) are distributed via Google Drive and have no
#    public raw URLs. The .txt presets are fetched separately by
#    tools/fetch_zapret_presets.py. winws2.exe starts without these
#    scripts - missing @lua references are ignored at load time.
# ----------------------------------------------------------------------
Log "[4/5] youtubediscord/zapret (additional resources)" "Yellow"
Log "  - presets and lua scripts are fetched by a separate step" "DarkGray"

# ----------------------------------------------------------------------
# 5. Flowseal/zapret-discord-youtube - v1 lists (LATEST release)
# ----------------------------------------------------------------------
Log "[5/5] Flowseal/zapret-discord-youtube (v1 lists) - querying latest release..." "Yellow"
$relF = Get-LatestRelease -Repo "Flowseal/zapret-discord-youtube"
if ($relF) {
    Log "  latest: $($relF.TagName) - $($relF.AssetName)" "Cyan"
    $flowZip = Join-Path $tempDir "zapret-discord-youtube-$($relF.TagName).zip"
    Download -Url $relF.AssetUrl -OutFile $flowZip -Description $relF.AssetName

    if (Test-Path $flowZip) {
        $flowExtract = Join-Path $tempDir "zapret-discord-youtube-$($relF.TagName)"
        ExtractZip -ZipPath $flowZip -DestDir $tempDir -Description $relF.AssetName
        # Flowseal archive extracts flat (no top-level folder); its lists/
        # directory lives directly in $tempDir.
        $flowLists = Join-Path $tempDir "lists"
        if (!(Test-Path $flowLists)) {
            $flowLists = Get-ChildItem -Path $tempDir -Directory -Recurse -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -eq "lists" } | Select-Object -First 1 -ExpandProperty FullName
        }
        if ($flowLists -and (Test-Path $flowLists)) {
            if (!(Test-Path $v1ListsDst)) { New-Item -ItemType Directory -Path $v1ListsDst -Force | Out-Null }
            foreach ($f in (Get-ChildItem -Path $flowLists -File)) {
                if ($f.Name -like "*-user.txt") { continue }
                $dst = Join-Path $v1ListsDst $f.Name
                if ((Test-Path $dst) -and -not $Force) { continue }
                Copy-Item -LiteralPath $f.FullName -Destination $dst -Force
            }
            Log "  - copied: Flowseal lists -> zapret\lists" "Green"
        } else {
            Log "  - lists/ directory not found in Flowseal archive" "Yellow"
        }
    }
} else {
    Log "  Could not determine latest Flowseal release" "Red"
}

# ----------------------------------------------------------------------
# Final report
# ----------------------------------------------------------------------
Log "" "White"
Log "============================================" "Cyan"
Log "Zapret setup complete." "Green"
Log "  v1 binaries: $v1BinDst" "DarkGray"
Log "  v1 lists:    $v1ListsDst" "DarkGray"
Log "  v2 binaries: $v2BinDst" "DarkGray"
Log "  v2 lists:    $v2ListsDst" "DarkGray"
Log "============================================" "Cyan"
