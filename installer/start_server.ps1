# POSHANE ASGI sunucusunu (HTTP + WebSocket) yerel ağda başlatır.
# Güncelleme sistemi releases\current dosyasıyla aktif sürümü belirler; yoksa kurulum klasörü kullanılır.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root "jetpos.env"
if (Test-Path $EnvFile) { Get-Content $EnvFile | Where-Object { $_ -match "^[A-Z_]+=" } | ForEach-Object { $k, $v = $_ -split "=", 2; Set-Item -Path "env:$k" -Value $v } }
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Port = if ($env:JETPOS_PORT) { $env:JETPOS_PORT } else { "8000" }
$DataDir = if ($env:JETPOS_DATA_DIR) { $env:JETPOS_DATA_DIR } else { Join-Path $Root "backend\data" }
$Backend = Join-Path $Root "backend"
$Pointer = Join-Path $DataDir "releases\current"
if (Test-Path $Pointer) {
  $ver = (Get-Content $Pointer -Raw).Trim()
  $rel = Join-Path $DataDir "releases\$ver\backend"
  if (Test-Path (Join-Path $rel "manage.py")) { $Backend = $rel; Write-Host "Aktif sürüm: $ver" }
}
Set-Location $Backend
& $Py manage.py migrate --noinput
& $Py -m daphne -b 0.0.0.0 -p $Port jetpos.asgi:application
