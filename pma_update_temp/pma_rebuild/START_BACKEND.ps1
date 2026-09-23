$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PMA_ADMIN_EMAIL = "ugoloevidence81@gmail.com"
$env:PMA_ADMIN_USERNAME = "PipsMaster"
$env:PMA_ADMIN_FULL_NAME = "Ugolo Evidence"
& "$env:LocalAppData\Programs\Python\Python314\python.exe" -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
