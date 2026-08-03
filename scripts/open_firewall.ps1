# Run ONCE on Computer 1 (as Administrator). Lets the other computer's agent
# and browsers on the LAN reach the server on TCP 8000.
New-NetFirewallRule -DisplayName "Thermal PoC server (TCP 8000)" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000
Write-Host "Done. Computer 2 can now reach http://$((Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '169.*' -and $_.IPAddress -ne '127.0.0.1'} | Select-Object -First 1).IPAddress):8000"
