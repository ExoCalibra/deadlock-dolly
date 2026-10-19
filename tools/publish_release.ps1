# Publish a built Deadlock Dolly release.
#
# Andrew runs this after committing and pushing the release commit. The agent
# never runs publishing commands. The script verifies the clean/pushed commit,
# the local artifacts and hashes, the validated release notes, and the absence
# of the tag before creating the GitHub release. Only the Windows ZIP is
# attached; the source ZIP remains a local build record.
#
# Example:
#   powershell -ExecutionPolicy Bypass -File tools/publish_release.ps1
#   powershell -ExecutionPolicy Bypass -File tools/publish_release.ps1 -DryRun
[CmdletBinding()]
param(
    [string]$Version = "0.6.61-alpha",
    [string]$Repository = "cravvnn/deadlock-dolly",
    [string]$Dist = "dist",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$tag = "v$Version"
$windowsZip = Join-Path $Dist "Deadlock_Dolly_${Version}_Windows_x64.zip"
$sourceZip = Join-Path $Dist "Deadlock_Dolly_${Version}_Source.zip"
$sumsPath = Join-Path $Dist "SHA256SUMS-$Version.txt"
$notesPath = Join-Path $Dist "GITHUB_RELEASE-$Version.md"

foreach ($required in @($windowsZip, $sourceZip)) {
    if (-not (Test-Path $required -PathType Leaf)) {
        throw "Missing release artifact: $required"
    }
}
if (-not (Test-Path $sumsPath -PathType Leaf)) {
    Copy-Item (Join-Path $Dist "SHA256SUMS.txt") $sumsPath
}
if (-not (Test-Path $notesPath -PathType Leaf)) {
    Copy-Item (Join-Path $root "docs/RELEASE_NOTES_$Version.md") $notesPath
}

# The release body must carry the current version and 2-4 Before/After bullets.
& py -3 tools/check_release_notes.py --version $Version
if ($LASTEXITCODE -ne 0) {
    throw "Release notes did not validate."
}

$expected = @{}
Get-Content $sumsPath | ForEach-Object {
    if ($_ -match '^([0-9a-fA-F]{64})\s+(.+?)\s*$') {
        $expected[$matches[2]] = $matches[1].ToLowerInvariant()
    }
}
foreach ($file in @($windowsZip, $sourceZip)) {
    $name = Split-Path -Leaf $file
    if (-not $expected.ContainsKey($name)) {
        throw "SHA256SUMS is missing $name"
    }
    $actual = (Get-FileHash $file -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected[$name]) {
        throw "SHA-256 mismatch for $name"
    }
    Write-Host ("OK  {0}  {1}" -f $actual, $name)
}

$dirty = git status --porcelain
if ($dirty) {
    throw "Working tree is not clean. Commit the release files before publishing."
}
$head = git rev-parse HEAD
$branch = git rev-parse --abbrev-ref HEAD
git fetch origin $branch | Out-Null
$remoteHead = git rev-parse "origin/$branch"
if ($head -ne $remoteHead) {
    throw "HEAD is not the pushed origin/$branch commit. Push first."
}
$existingTag = git ls-remote --tags origin "refs/tags/$tag"
if ($existingTag) {
    throw "Tag $tag already exists on origin."
}
gh auth status | Out-Null

Write-Host "Version:  $Version"
Write-Host "Commit:   $head ($branch)"
Write-Host "Tag:      $tag (will be created at the pushed commit)"
Write-Host "Attach:   $(Split-Path -Leaf $windowsZip)"
Write-Host "Notes:    $notesPath"
Write-Host "Source:   $(Split-Path -Leaf $sourceZip) (not attached)"

$arguments = @(
    "release", "create", $tag, $windowsZip,
    "--repo", $Repository,
    "--title", "Deadlock Dolly $Version",
    "--notes-file", $notesPath,
    "--latest=false",
    "--target", $head
)

if ($DryRun) {
    Write-Host "DRY RUN: gh $($arguments -join ' ')"
    return
}

& gh @arguments
if ($LASTEXITCODE -ne 0) {
    throw "gh release create failed."
}
gh release view $tag --repo $Repository --json url,assets
