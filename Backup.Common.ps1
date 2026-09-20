Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Read-Utf8Text {
    param([Parameter(Mandatory)][string]$Path)
    return [System.IO.File]::ReadAllText($Path)
}

function Write-Utf8Text {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Text)
    [System.IO.File]::WriteAllText($Path, $Text, [System.Text.UTF8Encoding]::new($false))
}

function Get-XmlTagText {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Tag)
    $text = Read-Utf8Text $Path
    $match = [regex]::Match($text, ('(?is)<' + [regex]::Escape($Tag) + '\b[^>]*>\s*([^<]+?)\s*</' + [regex]::Escape($Tag) + '>'))
    if (-not $match.Success) { throw "<$Tag> が見つかりません: $Path" }
    return $match.Groups[1].Value.Trim()
}

function Set-XmlTagText {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Tag, [Parameter(Mandatory)][string]$Value, [switch]$Optional)
    $text = Read-Utf8Text $Path
    $pattern = '(?is)(<' + [regex]::Escape($Tag) + '\b[^>]*>)\s*[^<]*?\s*(</' + [regex]::Escape($Tag) + '>)'
    $match = [regex]::Match($text, $pattern)
    if (-not $match.Success) {
        if ($Optional) { return $false }
        throw "<$Tag> が見つかりません: $Path"
    }
    $replacement = $match.Groups[1].Value + $Value + $match.Groups[2].Value
    $updated = $text.Substring(0, $match.Index) + $replacement + $text.Substring($match.Index + $match.Length)
    Write-Utf8Text -Path $Path -Text $updated
    return $true
}

function Get-JsonVersion {
    param([Parameter(Mandatory)][string]$Path)
    $json = (Read-Utf8Text $Path) | ConvertFrom-Json
    $value = [string]$json.version
    if ([string]::IsNullOrWhiteSpace($value)) { throw "version が見つかりません: $Path" }
    return $value.Trim()
}

function Set-JsonVersion {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Value)
    $text = Read-Utf8Text $Path
    $pattern = '(?m)("version"\s*:\s*")[^"]+("\s*,?)'
    $match = [regex]::Match($text, $pattern)
    if (-not $match.Success) { throw "version が見つかりません: $Path" }
    $replacement = $match.Groups[1].Value + $Value + $match.Groups[2].Value
    Write-Utf8Text -Path $Path -Text ($text.Substring(0, $match.Index) + $replacement + $text.Substring($match.Index + $match.Length))
}

function Get-NextVersion {
    param([Parameter(Mandatory)][string]$Version)
    $parts = $Version.Trim().TrimStart('v', 'V').Split('.')
    if ($parts.Count -lt 2 -or $parts.Count -gt 4) { throw "バージョン形式を解釈できません: $Version" }
    foreach ($part in $parts) { if ($part -notmatch '^\d+$') { throw "数値バージョンではありません: $Version" } }
    $lastWidth = $parts[-1].Length
    $parts[-1] = ([int]$parts[-1] + 1).ToString(('0' * $lastWidth))
    return ($parts -join '.')
}

function Get-AssemblyVersion {
    param([Parameter(Mandatory)][string]$Version)
    $numbers = @($Version.Trim().TrimStart('v', 'V').Split('.') | ForEach-Object { [int]$_ })
    while ($numbers.Count -lt 3) { $numbers += 0 }
    if ($numbers.Count -gt 3) { $numbers = $numbers[0..2] }
    return (($numbers + 0) -join '.')
}

function Get-ProjectVersion {
    param([Parameter(Mandatory)][string]$ProjectRoot, [Parameter(Mandatory)][string]$AppName)
    switch ($AppName) {
        'dropMP3'   { return Get-XmlTagText (Join-Path $ProjectRoot '_conf\app_version.xml') 'version' }
        'dropMP4'   { return Get-XmlTagText (Join-Path $ProjectRoot '_conf\app_version.xml') 'version' }
        'MvStock'   { return Get-XmlTagText (Join-Path $ProjectRoot 'version.xml') 'Version' }
        'MvFiler'   { return Get-XmlTagText (Join-Path $ProjectRoot 'version.xml') 'Version' }
        'MvSuite'   { return Get-XmlTagText (Join-Path $ProjectRoot 'version.xml') 'Version' }
        'MvView'    { return Get-XmlTagText (Join-Path $ProjectRoot 'version.xml') 'Version' }
        'WinSpliter'{ return Get-XmlTagText (Join-Path $ProjectRoot 'WinSpliter\WinSpliter.csproj') 'Version' }
        'MvSticky'  { return Get-JsonVersion (Join-Path $ProjectRoot 'mobile-pwa\package.json') }
        'WinPicker' { return Get-XmlTagText (Join-Path $ProjectRoot 'WinPicker\VersionInfo.xml') 'Version' }
        'TapoCtrl'  { return Get-XmlTagText (Join-Path $ProjectRoot 'Directory.Build.props') 'TapoCtrlVersion' }
        default     { throw "未対応のプロジェクトです: $AppName" }
    }
}

function Set-CsprojVersion {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Version, [switch]$PadProjectVersion)
    $projectVersion = if ($PadProjectVersion -and $Version.Split('.').Count -eq 2) { "$Version.0" } else { $Version }
    $assemblyVersion = Get-AssemblyVersion $projectVersion
    Set-XmlTagText $Path 'Version' $projectVersion | Out-Null
    Set-XmlTagText $Path 'AssemblyVersion' $assemblyVersion | Out-Null
    Set-XmlTagText $Path 'FileVersion' $assemblyVersion | Out-Null
    Set-XmlTagText $Path 'InformationalVersion' $Version -Optional | Out-Null
}

function Set-ProjectVersion {
    param([Parameter(Mandatory)][string]$ProjectRoot, [Parameter(Mandatory)][string]$AppName, [Parameter(Mandatory)][string]$OldVersion, [Parameter(Mandatory)][string]$NewVersion)
    if ($NewVersion -notmatch '^\d+(?:\.\d+){1,3}$') { throw "バージョンは 0.7.11 のような数値形式で指定してください: $NewVersion" }
    switch ($AppName) {
        'dropMP3' {
            Set-XmlTagText (Join-Path $ProjectRoot '_conf\app_version.xml') 'version' $NewVersion | Out-Null
            $legacy = Join-Path $ProjectRoot '_conf\app_version.json'; if (Test-Path -LiteralPath $legacy) { Set-JsonVersion $legacy $NewVersion }
            $py = Join-Path $ProjectRoot 'dropMP3.py'; if (Test-Path -LiteralPath $py) { $s=Read-Utf8Text $py; $s=$s -replace ('APP_VERSION_FALLBACK\s*=\s*"' + [regex]::Escape($OldVersion) + '"'), ('APP_VERSION_FALLBACK = "' + $NewVersion + '"'); Write-Utf8Text $py $s }
        }
        'dropMP4' {
            Set-XmlTagText (Join-Path $ProjectRoot '_conf\app_version.xml') 'version' $NewVersion | Out-Null
            $legacy = Join-Path $ProjectRoot '_conf\app_version.json'; if (Test-Path -LiteralPath $legacy) { Set-JsonVersion $legacy $NewVersion }
            $py = Join-Path $ProjectRoot 'dropmp4\app\window.py'; if (Test-Path -LiteralPath $py) { $s=Read-Utf8Text $py; $s=$s -replace ('APP_VERSION_FALLBACK\s*=\s*"' + [regex]::Escape($OldVersion) + '"'), ('APP_VERSION_FALLBACK = "' + $NewVersion + '"'); Write-Utf8Text $py $s }
        }
        { $_ -in @('MvStock','MvFiler','MvSuite','MvView') } {
            $path = Join-Path $ProjectRoot 'version.xml'
            Set-XmlTagText $path 'Version' $NewVersion | Out-Null
            Set-XmlTagText $path 'DisplayVersion' ("v$NewVersion") -Optional | Out-Null
            Set-XmlTagText $path 'BuildDate' (Get-Date -Format 'yyyy-MM-dd') -Optional | Out-Null
        }
        'WinSpliter' { Set-CsprojVersion (Join-Path $ProjectRoot 'WinSpliter\WinSpliter.csproj') $NewVersion }
        'MvSticky' {
            Set-JsonVersion (Join-Path $ProjectRoot 'mobile-pwa\package.json') $NewVersion
            Set-CsprojVersion (Join-Path $ProjectRoot 'MvSticky.csproj') $NewVersion
            Set-CsprojVersion (Join-Path $ProjectRoot 'tools\SamplePackManager\SamplePackManager.csproj') $NewVersion
            $board = Join-Path $ProjectRoot 'mobile-pwa\src\views\BoardView.vue'
            if (Test-Path -LiteralPath $board) {
                $s = Read-Utf8Text $board
                $s = $s.Replace("ApplicationVersion:'$OldVersion'", "ApplicationVersion:'$NewVersion'")
                Write-Utf8Text $board $s
            }
        }
        'WinPicker' {
            Set-XmlTagText (Join-Path $ProjectRoot 'WinPicker\VersionInfo.xml') 'Version' $NewVersion | Out-Null
            Set-CsprojVersion (Join-Path $ProjectRoot 'WinPicker\WinPicker.csproj') $NewVersion -PadProjectVersion
        }
        'TapoCtrl' {
            $path = Join-Path $ProjectRoot 'Directory.Build.props'
            Set-XmlTagText $path 'TapoCtrlVersion' $NewVersion | Out-Null
            $assembly = Get-AssemblyVersion $NewVersion
            Set-XmlTagText $path 'AssemblyVersion' $assembly | Out-Null
            Set-XmlTagText $path 'FileVersion' $assembly | Out-Null
        }
    }
}

function Test-IsExcludedPath {
    param([Parameter(Mandatory)][string]$RelativePath)
    $normalized = $RelativePath.Replace('/', '\')
    $segments = $normalized.Split('\')
    $excludedDirectories = @(
        '.git','.vs','.vscode','.cache','.pslocal','bin','obj','build','artifacts','dist','release','publish',
        'node_modules','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','.venv','venv',
        '_oldsource','__oldsource','_sourcebackups','_buildlogs','_worker','_browser_profiles',
        'exports','_export_','_mvchash_','_mvconf_','suite','_samplesource'
    )
    foreach ($segment in $segments[0..([Math]::Max(0,$segments.Count-2))]) {
        if ($excludedDirectories -contains $segment.ToLowerInvariant()) { return $true }
    }
    $name = [System.IO.Path]::GetFileName($normalized)
    if ($name -match '^(?i:\.env(?:\..*)?)$' -and $name -notmatch '(?i:\.example$)') { return $true }
    if ($name -match '^(?i:BuildConfiguration\.json|secrets?\..*|credentials?\..*|appsettings\.(?:Development|Production)\.json)$') { return $true }
    $extension = [System.IO.Path]::GetExtension($name).ToLowerInvariant()
    if (@('.exe','.dll','.pdb','.zip','.7z','.rar','.pyc','.pyo','.log','.tmp','.temp','.cache','.dmp','.user','.suo') -contains $extension) { return $true }
    return $false
}

function Test-InBackupTarget {
    param([Parameter(Mandatory)][string]$AppName, [Parameter(Mandatory)][string]$Target, [Parameter(Mandatory)][string]$RelativePath)
    if ($AppName -ne 'MvSticky' -or $Target -eq 'All') { return $true }
    $normalized = $RelativePath.Replace('/', '\')
    if ($Target -eq 'PC') { return -not $normalized.StartsWith('mobile-pwa\', [System.StringComparison]::OrdinalIgnoreCase) }
    if ($Target -eq 'PWA') {
        if ($normalized.StartsWith('mobile-pwa\', [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
        return $normalized -in @('BuildPWA.ps1','build.ps1','Backup.ps1','Backup.Common.ps1','.gitignore','README.md','README_en.md')
    }
    return $false
}

function Add-ZipTextEntry {
    param([Parameter(Mandatory)]$Archive, [Parameter(Mandatory)][string]$EntryName, [Parameter(Mandatory)][string]$Text)
    $entry = $Archive.CreateEntry($EntryName, [System.IO.Compression.CompressionLevel]::Optimal)
    $stream = $entry.Open()
    try {
        $writer = [System.IO.StreamWriter]::new($stream, [System.Text.UTF8Encoding]::new($false))
        try { $writer.Write($Text) } finally { $writer.Dispose() }
    } finally { $stream.Dispose() }
}

function Invoke-ProjectBackup {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [Parameter(Mandatory)][string]$AppName,
        [ValidateSet('All','PC','PWA')][string]$Target = 'All',
        [switch]$Bump,
        [string]$SetVersion,
        [switch]$Preview
    )
    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path.TrimEnd('\')
    if ($AppName -ne 'MvSticky' -and $Target -ne 'All') { throw "$AppName は -Target All のみ対応しています。" }
    if ($Bump -and -not [string]::IsNullOrWhiteSpace($SetVersion)) { throw '-Bump と -SetVersion は同時に指定できません。' }

    $oldVersion = Get-ProjectVersion -ProjectRoot $ProjectRoot -AppName $AppName
    $newVersion = if (-not [string]::IsNullOrWhiteSpace($SetVersion)) { $SetVersion.Trim().TrimStart('v','V') } elseif ($Bump) { Get-NextVersion $oldVersion } else { $oldVersion }
    if ($Preview -and $newVersion -ne $oldVersion) {
        Write-Host "[Preview] Version: $oldVersion -> $newVersion" -ForegroundColor Yellow
    } elseif ($newVersion -ne $oldVersion) {
        Set-ProjectVersion -ProjectRoot $ProjectRoot -AppName $AppName -OldVersion $oldVersion -NewVersion $newVersion
        $verified = Get-ProjectVersion -ProjectRoot $ProjectRoot -AppName $AppName
        if ($verified -ne $newVersion) { throw "バージョン更新の検証に失敗しました: expected=$newVersion actual=$verified" }
    }

    $files = @(Get-ChildItem -LiteralPath $ProjectRoot -Recurse -Force -File | ForEach-Object {
        $relative = $_.FullName.Substring($ProjectRoot.Length).TrimStart('\')
        if (-not (Test-IsExcludedPath $relative) -and (Test-InBackupTarget -AppName $AppName -Target $Target -RelativePath $relative)) {
            [pscustomobject]@{ File = $_; Relative = $relative }
        }
    } | Sort-Object Relative)
    if ($files.Count -eq 0) { throw 'バックアップ対象ファイルがありません。' }

    $backupDir = Join-Path $ProjectRoot '_Oldsource'
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $targetSuffix = if ($AppName -eq 'MvSticky' -and $Target -ne 'All') { "_$Target" } else { '' }
    $baseName = "${AppName}_v${newVersion}${targetSuffix}_$stamp"
    $archivePath = Join-Path $backupDir ($baseName + '.zip')
    $counter = 2
    while (Test-Path -LiteralPath $archivePath) { $archivePath = Join-Path $backupDir ("${baseName}_$counter.zip"); $counter++ }
    $totalBytes = [int64](($files | ForEach-Object { $_.File.Length } | Measure-Object -Sum).Sum)

    Write-Host ''
    Write-Host '=== Project source/resource backup ===' -ForegroundColor Cyan
    Write-Host ("Project : {0}" -f $AppName)
    Write-Host ("Target  : {0}" -f $Target)
    Write-Host ("Version : {0}" -f $newVersion) -ForegroundColor Green
    if ($newVersion -ne $oldVersion) { Write-Host ("Updated : {0} -> {1}" -f $oldVersion, $newVersion) -ForegroundColor Yellow }
    Write-Host ("Files   : {0:N0}" -f $files.Count)
    Write-Host ("Size    : {0:N1} MB" -f ($totalBytes / 1MB))
    Write-Host ("Archive : {0}" -f $archivePath)

    if ($Preview) {
        Write-Host '[Preview] ファイル更新とZIP作成は行っていません。' -ForegroundColor Yellow
        return [pscustomobject]@{ AppName=$AppName; Target=$Target; Version=$newVersion; FileCount=$files.Count; ArchivePath=$archivePath; Preview=$true }
    }

    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $stream = [System.IO.File]::Open($archivePath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    try {
        $archive = [System.IO.Compression.ZipArchive]::new($stream, [System.IO.Compression.ZipArchiveMode]::Create, $false, [System.Text.Encoding]::UTF8)
        try {
            foreach ($item in $files) {
                $entryName = $item.Relative.Replace('\','/')
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $item.File.FullName, $entryName, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
            }
            $created = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
            $manifest = @(
                'BackupKind: SourceAndResourcesForAIHandoff',
                "AppName: $AppName",
                "Version: $newVersion",
                "Target: $Target",
                "CreatedAt: $created",
                "SourceRoot: $ProjectRoot",
                "FileCount: $($files.Count)",
                "UncompressedBytes: $totalBytes",
                '',
                '[Files]'
            ) + @($files.Relative)
            Add-ZipTextEntry $archive '_backup_manifest.txt' ($manifest -join "`r`n")
            $guide = @"
# AI handoff package: $AppName v$newVersion ($Target)

This archive is a source-and-resource backup, not a compiled release.
It includes code, project/build scripts, documentation, and visual resources such as PNG/ICO files.
Generated outputs, dependency caches, previous backups, archives, and likely secret files are intentionally excluded.

For another AI or developer:
1. Read `_backup_manifest.txt` for the exact version and included-file inventory.
2. Inspect README/build scripts before changing the project.
3. Preserve relative paths because embedded resources and build files may depend on them.
4. Run the project's existing build/tests after editing.
5. `Backup.ps1` supports a normal backup, `-Preview`, `-Bump`, and `-SetVersion x.y.z`.

MvSticky note: PC and PWA build paths are separate. `-Target PC`, `-Target PWA`, or `-Target All` controls package contents; version changes remain synchronized to satisfy the repository's version contract.
"@
            Add-ZipTextEntry $archive '_AI_HANDOFF.md' $guide
        } finally { $archive.Dispose() }
    } catch {
        $stream.Dispose()
        if (Test-Path -LiteralPath $archivePath) { Remove-Item -LiteralPath $archivePath -Force }
        throw
    } finally {
        if ($null -ne $stream) { $stream.Dispose() }
    }
    $zipInfo = Get-Item -LiteralPath $archivePath
    Write-Host ("Completed: {0}" -f $zipInfo.FullName) -ForegroundColor Green
    Write-Host ("Backup Version: v{0}" -f $newVersion) -ForegroundColor Green
    Write-Host ("ZIP Size: {0:N1} MB" -f ($zipInfo.Length / 1MB))
    return [pscustomobject]@{ AppName=$AppName; Target=$Target; Version=$newVersion; FileCount=$files.Count; ArchivePath=$zipInfo.FullName; Preview=$false }
}
