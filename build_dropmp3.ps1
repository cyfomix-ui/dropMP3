param(
    [string]$Script = ".\dropMp3.py",
    [string]$Name = "DropMp3",
    [string]$ExeIcon = ".\DropMp3.ico",
    # Best: specify .\DropMp3_2.png or .\DropMp3_splash.png. If omitted, the script searches automatically.
    [string]$SplashImage = "",
    [string]$SplashIcon = ".\DropMp3_2.ico",
    [switch]$NoSplash,
    [switch]$DebugConsole
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Resolve-RequiredPath([string]$PathText, [string]$Label) {
    if ([string]::IsNullOrWhiteSpace($PathText)) { throw "$Label is empty." }
    if (!(Test-Path -LiteralPath $PathText)) { throw "$Label not found: $PathText" }
    return (Resolve-Path -LiteralPath $PathText).Path
}

function First-ExistingPath([string[]]$Candidates) {
    foreach ($p in $Candidates) {
        if (![string]::IsNullOrWhiteSpace($p) -and (Test-Path -LiteralPath $p)) {
            return (Resolve-Path -LiteralPath $p).Path
        }
    }
    return $null
}

$scriptPath = Resolve-RequiredPath $Script "Source"
$iconPath = $null
if (Test-Path -LiteralPath $ExeIcon) {
    $iconPath = (Resolve-Path -LiteralPath $ExeIcon).Path
} else {
    Write-Warning "EXE icon not found. Continue without --icon: $ExeIcon"
}

# IMPORTANT:
# PyInstaller reads the --splash image again while executing the generated .spec.
# Keep the generated splash in the project root, not under a temporary/work directory.
$stableAssetDir = Join-Path $PSScriptRoot "pyinstaller_assets"
New-Item -ItemType Directory -Force -Path $stableAssetDir | Out-Null
$splashPng = Join-Path $stableAssetDir "DropMp3_boot_splash_hires.png"
$splashSource = $null

if (!$NoSplash) {
    $splashSource = First-ExistingPath @(
        $SplashImage,
        ".\DropMp3_splash.png",
        ".\DropMp3_2.png",
        ".\DropMp3.png",
        $SplashIcon
    )

    if ($null -eq $splashSource) {
        Write-Warning "Splash source not found. Put DropMp3_splash.png / DropMp3_2.png / DropMp3.png, or $SplashIcon. Continue without --splash."
        $splashPng = $null
    } else {
        Add-Type -AssemblyName System.Drawing

        $srcExt = [System.IO.Path]::GetExtension($splashSource).ToLowerInvariant()
        $srcBitmap = $null
        $srcIcon = $null

        if ($srcExt -eq ".ico") {
            $srcIcon = New-Object System.Drawing.Icon($splashSource, 256, 256)
            $srcBitmap = $srcIcon.ToBitmap()
            Write-Host "Splash source: $splashSource (ICO requested as 256x256; PNG is recommended for best quality)"
        } else {
            $srcBitmap = [System.Drawing.Image]::FromFile($splashSource)
            Write-Host "Splash source: $splashSource (image/PNG preferred)"
        }

        $canvasW = 720
        $canvasH = 360
        $canvas = New-Object System.Drawing.Bitmap($canvasW, $canvasH)
        $g = [System.Drawing.Graphics]::FromImage($canvas)
        $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
        $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
        $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
        $g.Clear([System.Drawing.Color]::FromArgb(13, 15, 22))

        $borderPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(60, 80, 110), 2)
        $rect = New-Object System.Drawing.Rectangle(8, 8, ($canvasW - 16), ($canvasH - 16))
        $g.DrawRectangle($borderPen, $rect)

        $box = 144
        $ratio = [Math]::Min($box / [double]$srcBitmap.Width, $box / [double]$srcBitmap.Height)
        $drawW = [int]([double]$srcBitmap.Width * $ratio)
        $drawH = [int]([double]$srcBitmap.Height * $ratio)
        $drawX = [int](($canvasW - $drawW) / 2)
        $drawY = 52 + [int](($box - $drawH) / 2)
        $g.DrawImage($srcBitmap, $drawX, $drawY, $drawW, $drawH)

        $fontTitle = New-Object System.Drawing.Font("Segoe UI", 30, [System.Drawing.FontStyle]::Bold)
        $fontSub = New-Object System.Drawing.Font("Segoe UI", 13, [System.Drawing.FontStyle]::Regular)
        $brushTitle = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
        $brushSub = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(210, 220, 235))
        $sf = New-Object System.Drawing.StringFormat
        $sf.Alignment = [System.Drawing.StringAlignment]::Center
        $titleRect = New-Object System.Drawing.RectangleF(0, 205, $canvasW, 48)
        $subRect = New-Object System.Drawing.RectangleF(0, 258, $canvasW, 28)
        $g.DrawString($Name, $fontTitle, $brushTitle, $titleRect, $sf)
        $g.DrawString("Starting player...", $fontSub, $brushSub, $subRect, $sf)

        if (Test-Path -LiteralPath $splashPng) { Remove-Item -LiteralPath $splashPng -Force }
        $canvas.Save($splashPng, [System.Drawing.Imaging.ImageFormat]::Png)

        $g.Dispose(); $canvas.Dispose(); $srcBitmap.Dispose()
        if ($srcIcon) { $srcIcon.Dispose() }

        if (!(Test-Path -LiteralPath $splashPng)) { throw "Splash PNG was not created: $splashPng" }
        Write-Host "Splash PNG created: $splashPng"
    }
}

python -m PyInstaller --version | Out-Host

$distDir = Join-Path $PSScriptRoot "dist"
$buildDir = Join-Path $PSScriptRoot "build"
$specPath = Join-Path $PSScriptRoot "$Name.spec"
if (Test-Path -LiteralPath $specPath) { Remove-Item -LiteralPath $specPath -Force }

$args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name", $Name,
    "--distpath", $distDir,
    "--workpath", $buildDir,
    "--specpath", $PSScriptRoot,
    "--noupx"
)

if (!$DebugConsole) { $args += "--windowed" }
if ($iconPath) { $args += @("--icon", $iconPath) }
if (!$NoSplash -and $splashPng -and (Test-Path -LiteralPath $splashPng)) { $args += @("--splash", $splashPng) }

# Runtime assets: include icons/images if your app refers to them.
if ($iconPath) { $args += @("--add-data", "$iconPath;.") }
if ($splashSource -and (Test-Path -LiteralPath $splashSource)) { $args += @("--add-data", "$splashSource;.") }
if ($splashPng -and (Test-Path -LiteralPath $splashPng)) { $args += @("--add-data", "$splashPng;.") }
if (Test-Path -LiteralPath ".\_conf") { $args += @("--add-data", "$((Resolve-Path -LiteralPath '.\_conf').Path);_conf") }

$args += @(
    "--collect-all", "PySide6",
    "--collect-all", "mutagen",
    $scriptPath
)

Write-Host ""
Write-Host "Building OneFile EXE with stable high-res splash..." -ForegroundColor Cyan
Write-Host "python $($args -join ' ')"
Write-Host ""
& python @args
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed. Exit code: $LASTEXITCODE" }

$exePath = Join-Path $distDir "$Name.exe"
if (Test-Path -LiteralPath $exePath) {
    $confSrc = Join-Path $PSScriptRoot "_conf"
    if (Test-Path -LiteralPath $confSrc) {
        $confOut = Join-Path $distDir "_conf"
        if (Test-Path -LiteralPath $confOut) {
            Remove-Item -LiteralPath $confOut -Recurse -Force
        }
        Copy-Item -LiteralPath $confSrc -Destination $confOut -Recurse -Force
        Write-Host "Runtime config/help copied: $confOut" -ForegroundColor Green
    }
    Write-Host ""
    Write-Host "DONE: $exePath" -ForegroundColor Green
} else {
    throw "Build finished but EXE was not found: $exePath"
}
