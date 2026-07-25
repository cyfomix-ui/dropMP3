param(
    [switch]$SkipAppBuild,
    [string]$OutputDirectory = ".\release"
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$versionXml = [xml](Get-Content -LiteralPath ".\_conf\app_version.xml" -Raw)
$version = [string]$versionXml.DropMp3Version.version
if ($version -notmatch '^\d+\.\d{2}$') {
    throw "_conf/app_version.xml の version は 1.02 のような形式で指定してください。現在値: $version"
}

if (-not $SkipAppBuild) {
    & ".\build.ps1"
    if ($LASTEXITCODE -ne 0) { throw "アプリ本体のビルドに失敗しました。" }
}

$isccCandidates = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

$iscc = $isccCandidates | Select-Object -First 1
if (-not $iscc) {
    throw "Inno Setup 6 Compiler (ISCC.exe) が見つかりません。https://jrsoftware.org/isdl.php から導入するか、winget install --id JRSoftware.InnoSetup を実行してください。"
}

$sourceDir = (Resolve-Path -LiteralPath ".\dist").Path
$outputDir = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $OutputDirectory))
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

& $iscc "/DMyAppVersion=$version" "/DMySourceDir=$sourceDir" "/DMyOutputDir=$outputDir" ".\installer\DropMP3.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup Compiler が終了コード $LASTEXITCODE で失敗しました。" }

$displayVersion = "Ver$version"
$setupPath = Join-Path $outputDir "DropMP3-Setup-$displayVersion-x64.exe"
if (-not (Test-Path -LiteralPath $setupPath)) { throw "Setupファイルが生成されませんでした: $setupPath" }
$hashPath = "$setupPath.sha256"
$hash = (Get-FileHash -LiteralPath $setupPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $hashPath -Encoding ascii -Value "$hash  $([IO.Path]::GetFileName($setupPath))"
$portablePath = Join-Path $outputDir "DropMP3-Portable-$displayVersion-x64.zip"
Compress-Archive -Path (Join-Path $sourceDir "DropMP3.exe"), (Join-Path $sourceDir "_conf") -DestinationPath $portablePath -Force
$portableHashPath = "$portablePath.sha256"
$portableHash = (Get-FileHash -LiteralPath $portablePath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $portableHashPath -Encoding ascii -Value "$portableHash  $([IO.Path]::GetFileName($portablePath))"
Write-Host "Setup: $setupPath" -ForegroundColor Green
Write-Host "SHA-256: $hashPath" -ForegroundColor Green
Write-Host "Portable: $portablePath" -ForegroundColor Green
Write-Host "SHA-256: $portableHashPath" -ForegroundColor Green
