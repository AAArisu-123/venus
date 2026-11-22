# Restrict Venus secrets and local chat data to the signed-in Windows user.
# Run from anywhere: powershell.exe -NoProfile -File .\scripts\harden_private_files.ps1
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name

$dataDir = Join-Path $root 'data'
if (Test-Path -LiteralPath $dataDir -PathType Container) {
    & icacls $dataDir /inheritance:r /grant:r "${user}:(OI)(CI)F" | Out-Null
}

$files = @()
$envPath = Join-Path $root '.env'
if (Test-Path -LiteralPath $envPath -PathType Leaf) {
    $files += $envPath
}
# Restrict every root-level .txt file too; this avoids depending on how
# PowerShell 5 decodes a non-ASCII filename stored in this script.
$files += Get-ChildItem -LiteralPath $root -Filter '*.txt' -File |
    ForEach-Object { $_.FullName }

foreach ($path in $files) {
    & icacls $path /inheritance:r /grant:r "${user}:F" | Out-Null
}

Write-Output 'Venus private files are now restricted to the current Windows user.'
