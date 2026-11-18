# JETPOS periyodik görevleri: otomatik yedek, saklama, geri yükleme testi, sağlık, yazdırma kuyruğu,
# senkronizasyon, hatırlatmalar, zamanlanmış raporlar, destek kayıt imhası.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root "jetpos.env"
if (Test-Path $EnvFile) { Get-Content $EnvFile | Where-Object { $_ -match "^[A-Z_]+=" } | ForEach-Object { $k, $v = $_ -split "=", 2; Set-Item -Path "env:$k" -Value $v } }
$Py = Join-Path $Root ".venv\Scripts\python.exe"
Set-Location (Join-Path $Root "backend")
& $Py manage.py jetpos_scheduler --interval 30
