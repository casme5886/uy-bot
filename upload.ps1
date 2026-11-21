# Bot fayllarini Oracle serverga yuklab, o'rnatishni ishga tushiradi.
# Ishlatish (PowerShell, E:\project\uy-bot papkasida):
#   .\upload.ps1 -Ip 123.45.67.89 -Key C:\Users\User\Downloads\ssh-key.key
param(
  [Parameter(Mandatory = $true)][string]$Ip,
  [Parameter(Mandatory = $true)][string]$Key,
  [string]$User = "ubuntu"
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Windows SSH kalit fayliga "faqat siz o'qiy olasiz" ruxsatini beramiz (aks holda ssh rad etadi)
icacls $Key /inheritance:r | Out-Null
icacls $Key /grant:r "$($env:USERNAME):(R)" | Out-Null

$target = "$User@$Ip"
Write-Host "== Serverda papka yaratilmoqda ==" -ForegroundColor Cyan
ssh -i $Key -o StrictHostKeyChecking=accept-new $target "mkdir -p ~/uy-bot"

Write-Host "== Fayllar yuklanmoqda ==" -ForegroundColor Cyan
$files = @("bot.py", ".env", "setup.sh")
if (Test-Path "seen.db") { $files += "seen.db" }
if (Test-Path "settings.json") { $files += "settings.json" }
scp -i $Key $files "${target}:~/uy-bot/"

Write-Host "== O'rnatish boshlandi (2-3 daqiqa) ==" -ForegroundColor Cyan
ssh -i $Key $target "bash ~/uy-bot/setup.sh"
