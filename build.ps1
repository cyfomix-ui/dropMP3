# build_exe.ps1
# DropMp3 を PyInstaller で exe 化するスクリプト
# dropMp3.py と同じフォルダに置いて実行してください。

$ErrorActionPreference = "Stop"

# ==============================
# 設定
# ==============================
$AppName = "DropMP3"
$MainPy  = "dropMP3.py"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MainPath = Join-Path $RootDir $MainPy
$DistDir = Join-Path $RootDir "dist"
$BuildDir = Join-Path $RootDir "build"
$SpecPath = Join-Path $RootDir "$AppName.spec"
$IconPath = Join-Path $RootDir "DropMP3.ico"
$AboutImagePath = Join-Path $RootDir "DropMP3_about.png"
$SplashPng = Join-Path $RootDir "pyinstaller_assets\DropMP3_boot_splash_hires.png"
if (!(Test-Path -LiteralPath $SplashPng)) {
    $SplashPng = Join-Path $RootDir "DropMP3_boot_splash.png"
}

Write-Host "========================================"
Write-Host " DropMP3 EXE Builder"
Write-Host "========================================"
Write-Host "RootDir : $RootDir"
Write-Host "MainPy  : $MainPath"
Write-Host ""

# ==============================
# Python確認
# ==============================
Write-Host "[1/6] Python確認..."
python --version

if (!(Test-Path $MainPath)) {
    throw "メインスクリプトが見つかりません: $MainPath"
}

if (!(Test-Path -LiteralPath $IconPath)) {
    throw "EXEアイコンが見つかりません: $IconPath"
}

if (!(Test-Path -LiteralPath $AboutImagePath)) {
    throw "About画像が見つかりません: $AboutImagePath"
}

# ==============================
# 必要パッケージ確認・Install
# ==============================
Write-Host ""
Write-Host "[2/6] 必要パッケージを確認/インストール..."

python -m pip install --upgrade pip
python -m pip install -r (Join-Path $RootDir "requirements-build.txt")

# ==============================
# 古いビルド削除
# ==============================
Write-Host ""
Write-Host "[3/6] 古いビルドファイルを削除..."

if (Test-Path $DistDir) {
    Remove-Item $DistDir -Recurse -Force
}

if (Test-Path $BuildDir) {
    Remove-Item $BuildDir -Recurse -Force
}

if (Test-Path $SpecPath) {
    Remove-Item $SpecPath -Force
}

# ==============================
# PyInstaller実行
# ==============================
Write-Host ""
Write-Host "[4/6] PyInstallerでexe作成..."

python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --name $AppName `
    --icon "$IconPath" `
    --splash "$SplashPng" `
    --collect-all PySide6 `
    --collect-all mutagen `
    --hidden-import PySide6.QtMultimedia `
    --hidden-import PySide6.QtMultimediaWidgets `
    --hidden-import PySide6.QtNetwork `
    --hidden-import PySide6.QtSvg `
    --hidden-import mutagen.mp3 `
    --hidden-import mutagen.flac `
    --hidden-import mutagen.mp4 `
    --hidden-import mutagen.oggvorbis `
    --hidden-import mutagen.wave `
    --add-data "$IconPath;." `
    --add-data "$AboutImagePath;." `
    --add-data "$SplashPng;." `
    --add-data "$((Resolve-Path -LiteralPath '.\_conf\app_version.xml').Path);_conf" `
    $MainPath

# ==============================
# 結果確認
# ==============================
Write-Host ""
Write-Host "[5/6] 作成結果確認..."

$ExePath = Join-Path $DistDir "$AppName.exe"

if (!(Test-Path $ExePath)) {
    throw "exe作成に失敗しました: $ExePath"
}

Write-Host ""
Write-Host "EXE作成完了:"
Write-Host $ExePath

$ConfSrc = Join-Path $PSScriptRoot "_conf"
if (Test-Path -LiteralPath $ConfSrc) {
    $ConfOut = Join-Path $DistDir "_conf"
    if (Test-Path -LiteralPath $ConfOut) {
        Remove-Item -LiteralPath $ConfOut -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $ConfOut | Out-Null
    Copy-Item -LiteralPath (Join-Path $ConfSrc "app_version.xml") -Destination $ConfOut -Force
    $HtmlSrc = Join-Path $ConfSrc "html"
    if (Test-Path -LiteralPath $HtmlSrc) {
        Copy-Item -LiteralPath $HtmlSrc -Destination $ConfOut -Recurse -Force
    }
    Write-Host "配布用バージョン情報/Helpをコピーしました:"
    Write-Host $ConfOut
}

# ==============================
# distを開く
# ==============================
Write-Host ""
Write-Host "[6/6] distフォルダを開きます..."
if (-not $env:CI) {
    Start-Process explorer.exe $DistDir
}

Write-Host ""
Write-Host "========================================"
Write-Host " 完了"
Write-Host "========================================"
