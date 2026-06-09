# Run PowerShell as Administrator: right-click → Run as administrator
# Allows inbound TCP 8000 on private networks (same Wi‑Fi clients)

$ruleName = "Multi-Image Asset API (TCP 8000)"

$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Firewall rule already exists: $ruleName"
} else {
    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort 8000 `
        -Profile Any
    Write-Host "Created firewall rule: $ruleName (Private profile, port 8000)"
}

Write-Host "Done. Restart the API with: python serve.py"
