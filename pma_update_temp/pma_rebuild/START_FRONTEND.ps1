$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "frontend")
& "$env:LocalAppData\Programs\Python\Python314\python.exe" -m http.server 5500
