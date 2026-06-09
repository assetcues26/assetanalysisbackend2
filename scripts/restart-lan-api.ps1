# Stops anything on port 8000, opens firewall, starts API on 0.0.0.0
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "Stopping processes listening on port 8000..."
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        Write-Host "  Stopped PID $($_.OwningProcess)"
    }
Start-Sleep -Seconds 1

$fwScript = Join-Path $PSScriptRoot "open-firewall.ps1"
if (-not (Get-NetFirewallRule -DisplayName "Multi-Image Asset API (TCP 8000)" -ErrorAction SilentlyContinue)) {
    Write-Host "Adding firewall rule (needs Administrator)..."
    try {
        Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$fwScript`"" -Wait
    } catch {
        Write-Host "Could not auto-elevate. Run as Admin: .\scripts\open-firewall.ps1"
    }
}

$ip = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.InterfaceAlias -eq "Wi-Fi" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -First 1 -ExpandProperty IPAddress)

Write-Host ""
if ($ip) {
    Write-Host "After start, open on your phone: http://${ip}:8000/docs"
}
Write-Host ""

if (Test-Path ".venv\Scripts\python.exe") {
    & .\.venv\Scripts\python.exe serve.py
} else {
    python serve.py
}
