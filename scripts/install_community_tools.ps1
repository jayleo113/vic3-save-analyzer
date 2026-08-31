param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"
$community = Join-Path $Root "community"
New-Item -ItemType Directory -Force -Path $community | Out-Null

function Clone-Or-Pull($Url, $Name) {
    $target = Join-Path $community $Name
    if (Test-Path (Join-Path $target ".git")) {
        git -C $target pull --ff-only
    } elseif (Test-Path $target) {
        Write-Host "$target exists but is not a git repository; skipping."
    } else {
        git clone $Url $target
    }
}

Clone-Or-Pull "https://github.com/OakenTrader/Garibaldi.git" "Garibaldi"
Clone-Or-Pull "https://github.com/RobertoTCo/vic3-reader.git" "vic3-reader"

Write-Host "Community tools installed under $community"
