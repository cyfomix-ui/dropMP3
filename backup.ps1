<#
.SYNOPSIS
  Source/resource backup for AI handoff.
.DESCRIPTION
  Creates one versioned ZIP under .\_Oldsource. Build outputs, caches, old backups,
  archives, and likely secret files are excluded. The ZIP includes a manifest and AI guide.
.PARAMETER Bump
  Increment the final numeric component before backup (0.7.10 -> 0.7.11, 1.09 -> 1.10).
.PARAMETER SetVersion
  Set an exact version before backup. Cannot be combined with -Bump.
.PARAMETER Target
  MvSticky only: All, PC, or PWA. Other projects use All.
.PARAMETER Preview
  Show version, file count, and output path without changing files or creating a ZIP.
.EXAMPLE
  .\Backup.ps1
.EXAMPLE
  .\Backup.ps1 -Bump
.EXAMPLE
  .\Backup.ps1 -SetVersion 0.8.00
.EXAMPLE
  .\Backup.ps1 -Target PWA -Preview
#>
[CmdletBinding()]
param(
    [ValidateSet('All','PC','PWA')][string]$Target = 'All',
    [switch]$Bump,
    [string]$SetVersion,
    [switch]$Preview
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Backup.Common.ps1')

$appName = Split-Path -Leaf $PSScriptRoot
Invoke-ProjectBackup -ProjectRoot $PSScriptRoot -AppName $appName -Target $Target -Bump:$Bump -SetVersion $SetVersion -Preview:$Preview
