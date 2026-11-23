<#
.SYNOPSIS
  USB/offline güncelleme: imzalı paketi doğrular, yönetici onayı ister, yedek alır, uygular, sağlık testi yapar;
  başarısızlıkta otomatik geri alır.
.EXAMPLE
  .\update_offline.ps1 -Package E:\jetpos-1.1.0.zip -Signature E:\jetpos-1.1.0.zip.sig
#>
param([Parameter(Mandatory)][string]$Package, [Parameter(Mandatory)][string]$Signature)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root "jetpos.env"
if (Test-Path $EnvFile) { Get-Content $EnvFile | Where-Object { $_ -match "^[A-Z_]+=" } | ForEach-Object { $k, $v = $_ -split "=", 2; Set-Item -Path "env:$k" -Value $v } }
$Py = Join-Path $Root ".venv\Scripts\python.exe"
Set-Location (Join-Path $Root "backend")
& $Py manage.py jetpos_update stage --package $Package --signature $Signature
$ans = Read-Host "Güncelleme doğrulandı. Uygulansın mı? (önce otomatik yedek alınır) [e/H]"
if ($ans -notin @("e", "E", "evet")) { Write-Host "İptal edildi."; exit 1 }
& $Py manage.py jetpos_update apply --latest --yes
Write-Host "Sunucuyu yeniden başlatın: Görev Zamanlayıcı > 'POSHANE Sunucu' > Yeniden başlat"
