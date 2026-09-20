$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -Force
Write-Host '1 - Vercel AI Gateway (varsayilan)'
Write-Host '2 - TypeSafe dogrudan'
$providerChoice = Read-Host 'Saglayici [1]'
if ($providerChoice -notin @('', '1', '2')) { throw 'Gecersiz saglayici.' }
$provider = if ($providerChoice -eq '2') { 'typesafe' } else { 'vercel' }
$keyName = if ($provider -eq 'vercel') { 'vercel-key.dpapi' } else { 'jev-key.dpapi' }
Write-Host 'Sectiginiz saglayicinin API anahtarini yapistirin. Karakterler gizlenir.'
$secret = Read-Host 'API anahtari' -AsSecureString
if ($secret.Length -lt 20) { $secret.Dispose(); throw 'Anahtar bos veya cok kisa. Kaydedilmedi.' }
$configPath = Join-Path $PSScriptRoot '..\config'
New-Item -ItemType Directory -Force -Path $configPath | Out-Null
try { $secret | ConvertFrom-SecureString | Set-Content -LiteralPath (Join-Path $configPath $keyName) -Encoding ASCII }
finally { $secret.Dispose() }
[IO.File]::WriteAllText((Join-Path $configPath 'provider.json'), ('{"provider":"' + $provider + '"}'))
Write-Host 'Kaydedildi. Anahtar bu Windows kullanicisinin DPAPI korumasiyla sifrelendi.'
