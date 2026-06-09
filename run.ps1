# Run API on all interfaces so other devices on the same Wi‑Fi can connect.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Create venv first: python -m venv .venv && .\.venv\Scripts\pip install -r requirements.txt"
    exit 1
}

$ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object -First 1 -ExpandProperty IPAddress)

Write-Host "Starting API on 0.0.0.0:8000 (all network interfaces)"
if ($ip) {
    Write-Host "Others on your Wi-Fi can use: http://${ip}:8000/docs"
    Write-Host "Analyze endpoint:         http://${ip}:8000/v1/assets/analyze"
}
Write-Host "Press Ctrl+C to stop."
Write-Host ""

.\.venv\Scripts\python.exe serve.py
