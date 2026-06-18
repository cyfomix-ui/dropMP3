param(
    [string]$TargetDir = ".",
    [string]$BackupDirName = "oldsource"
)

$ErrorActionPreference = "Stop"

# 対象フォルダを解決
$target = Resolve-Path -LiteralPath $TargetDir
$targetPath = $target.Path

# バックアップ先 oldsource
$backupDir = Join-Path $targetPath $BackupDirName
if (-not (Test-Path -LiteralPath $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir | Out-Null
}

# 日付時間付きZIP名
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$zipName = "DropMp3_$stamp.zip"
$zipPath = Join-Path $backupDir $zipName

# 一時作業フォルダ
$tempRoot = Join-Path $env:TEMP "DropMp3_backup_$stamp"
if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $tempRoot | Out-Null

try {
    Write-Host "==== DropMp3 source backup ===="
    Write-Host "Target : $targetPath"
    Write-Host "Output : $zipPath"
    Write-Host ""

    # バックアップ対象
    # pyソース、ps1、アイコン、画像ファイル
    $patterns = @(
        "*.py",
        "*.ps1",
        "*.ico",
        "*.png",
        "*.jpg",
        "*.jpeg",
        "*.webp",
        "*.bmp",
        "*.gif"
    )

    $files = @()

    foreach ($pattern in $patterns) {
        $files += Get-ChildItem -LiteralPath $targetPath -File -Filter $pattern -ErrorAction SilentlyContinue
    }

    # 重複除去
    $files = $files | Sort-Object FullName -Unique

    if (-not $files -or $files.Count -eq 0) {
        throw "バックアップ対象ファイルが見つかりませんでした。"
    }

    Write-Host "Backup files:"
    foreach ($file in $files) {
        Write-Host "  $($file.Name)"
        Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $tempRoot $file.Name) -Force
    }

    # メモ情報も一緒に入れる
    $manifest = Join-Path $tempRoot "_backup_manifest.txt"
    @(
        "DropMp3 backup"
        "Created : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        "Source  : $targetPath"
        "Output  : $zipPath"
        ""
        "Files:"
        ($files | ForEach-Object { " - $($_.Name)  $($_.Length) bytes  $($_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))" })
    ) | Set-Content -LiteralPath $manifest -Encoding UTF8

    # 既存ZIPがあれば消す
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }

    Compress-Archive -Path (Join-Path $tempRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal

    Write-Host ""
    Write-Host "Backup complete."
    Write-Host $zipPath
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
