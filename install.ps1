# Instalador do J' PZ MAP STUDIO para Windows (PowerShell 5.1+). Rode pelo install.cmd (duplo clique).
# Baixa o Python portatil (python-build-standalone, versao fixa, sha256 conferido), instala as wheels
# prontas que vieram no pacote e monta "J' PZ MAP STUDIO.exe" NESTA maquina (sem compilador, sem SDK)
# + atalhos na Area de Trabalho e no Menu Iniciar. Arquivo so com ASCII (o PS 5.1 le sem BOM como ANSI).
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\jpzmapstudio'),
    [switch]$NoLaunch,
    [switch]$NoShortcuts
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # sem isso o Invoke-WebRequest do PS 5.1 fica lentissimo

$AppName = "J' PZ MAP STUDIO"
$PbsTag = '20261124'
$PyVer = '3.12.16'
$Sha = '96694b50dcfde13d56e40346ddaa552a9cd650290e9b933cecf83c1d82226960'
$Target = 'win-x64'
$Tarball = "cpython-$PyVer+$PbsTag-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
$Url = "https://github.com/astral-sh/python-build-standalone/releases/download/$PbsTag/" + $Tarball.Replace('+', '%2B')
$Src = $PSScriptRoot
$Cache = Join-Path $env:LOCALAPPDATA 'jpzmapstudio\dl'

# idioma das mensagens: o idioma da interface do Windows (pt = portugues, o resto = ingles)
$En = $true
try { $En = ((Get-UICulture).TwoLetterISOLanguageName -ne 'pt') } catch { $En = $true }
function T([string]$TextPt, [string]$TextEn) { if ($script:En) { return $TextEn } else { return $TextPt } }

function Fail([string]$msg) {
    Write-Host ''
    Write-Host ((T 'ERRO' 'ERROR') + ": $msg") -ForegroundColor Red
    exit 1
}

function Test-Sha([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return $false }
    return ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower() -eq $Sha)
}

Write-Host ("== $AppName : " + (T 'instalador Windows' 'Windows installer'))
$arch = $env:PROCESSOR_ARCHITEW6432
if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
if ($arch -eq 'ARM64') { Write-Host (T '-- Windows ARM64: usando o runtime x64 (emulacao do Windows 11).' '-- Windows ARM64: using the x64 runtime (Windows 11 emulation).') }
elseif ($arch -ne 'AMD64') { Fail (T "arquitetura nao suportada: $arch (precisa Windows 64 bits)" "unsupported architecture: $arch (needs 64-bit Windows)") }

if (-not (Test-Path -LiteralPath (Join-Path $Src 'app\pzms\main.py'))) { Fail (T "pacote incompleto (falta app\pzms\main.py em $Src)" "incomplete package (app\pzms\main.py missing in $Src)") }
if (-not (Test-Path -LiteralPath (Join-Path $Src 'launcher\build.py'))) { Fail (T 'pacote incompleto (falta launcher\build.py)' 'incomplete package (launcher\build.py missing)') }
$tarExe = Join-Path $env:SystemRoot 'System32\tar.exe'
if (-not (Test-Path -LiteralPath $tarExe)) { Fail (T 'tar.exe nao encontrado (precisa Windows 10 1803 ou mais novo)' 'tar.exe not found (needs Windows 10 1803 or newer)') }

New-Item -ItemType Directory -Force -Path $Cache | Out-Null
$tgz = Join-Path $Cache $Tarball
$bundled = Join-Path $Src "runtime\$Tarball"
if (Test-Sha $bundled) {
    $tgz = $bundled
} elseif (-not (Test-Sha $tgz)) {
    Write-Host (T "-- baixando Python $PyVer portatil..." "-- downloading portable Python $PyVer...")
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
    $part = "$tgz.part"
    try {
        Invoke-WebRequest -Uri $Url -OutFile $part -UseBasicParsing
    } catch {
        Fail ((T "download do Python falhou" "Python download failed") + " ($Url): $($_.Exception.Message)")
    }
    Move-Item -LiteralPath $part -Destination $tgz -Force
    if (-not (Test-Sha $tgz)) {
        Remove-Item -LiteralPath $tgz -Force
        Fail (T 'sha256 do Python nao confere (download corrompido ou adulterado)' 'Python sha256 does not match (corrupted or tampered download)')
    }
}
Write-Host (T '-- Python conferido (sha256 ok)' '-- Python verified (sha256 ok)')

# o app aberto trava os arquivos: pede para fechar antes
# aberto: pede para salvar o projeto e fechar (/api/shutdown); depois reabre de onde parou
function Get-Running { @(Get-Process -Name python, pythonw -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and $_.Path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase) }) }
function Wait-Exit([int]$n) { for ($i = 0; $i -lt $n; $i++) { if ((Get-Running).Count -eq 0) { return $true }; Start-Sleep -Milliseconds 500 }; return ((Get-Running).Count -eq 0) }
$Resume = $false
if ((Get-Running).Count -gt 0) {
    Write-Host (T "-- $AppName aberto: salvando o projeto e fechando para atualizar..." "-- $AppName is open: saving the project and closing it to update...")
    $Resume = $true
    $runf = Join-Path $env:APPDATA 'jpzmapstudio\running.json'
    try {
        $port = (Get-Content -LiteralPath $runf -Raw | ConvertFrom-Json).port
        Invoke-WebRequest -UseBasicParsing -Method Post -Uri "http://127.0.0.1:$port/api/shutdown" -Body '{}' -ContentType 'application/json' -TimeoutSec 20 | Out-Null
    } catch { }
    if (-not (Wait-Exit 20)) {
        # versao antiga (sem /api/shutdown): fecha a janela; o app salva o projeto ao fechar
        Get-Running | ForEach-Object { [void]$_.CloseMainWindow() }
        if (-not (Wait-Exit 40)) { Fail (T "nao consegui fechar o $AppName; feche a janela e rode o instalador de novo" "could not close $AppName; close the window and run the installer again") }
    }
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
foreach ($d in @('python', 'app')) {
    $p = Join-Path $InstallDir $d
    if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force }
}
Write-Host (T '-- extraindo o Python...' '-- extracting Python...')
$ErrorActionPreference = 'Continue'   # PS 5.1: stderr de programa nativo nao pode virar erro fatal
& $tarExe -xzf $tgz -C $InstallDir
if ($LASTEXITCODE -ne 0) { Fail ((T "tar.exe falhou (codigo" "tar.exe failed (code") + " $LASTEXITCODE)") }
$py = Join-Path $InstallDir 'python\python.exe'
if (-not (Test-Path -LiteralPath $py)) { Fail (T 'Python extraido incompleto' 'extracted Python is incomplete') }

Write-Host (T '-- instalando dependencias prontas e montando o executavel...' '-- installing bundled dependencies and building the executable...')
& $py -I (Join-Path $Src 'launcher\build.py') --target $Target --src $Src --home $InstallDir
if ($LASTEXITCODE -ne 0) { Fail ((T "montagem falhou (codigo" "build failed (code") + " $LASTEXITCODE)") }
$ErrorActionPreference = 'Stop'

$exe = Join-Path $InstallDir "$AppName.exe"
$ico = Join-Path $InstallDir 'icon.ico'
if (-not (Test-Path -LiteralPath $exe)) { Fail (T 'executavel nao foi criado' 'the executable was not created') }

if (-not $NoShortcuts) {
    $shell = New-Object -ComObject WScript.Shell
    $places = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
    foreach ($dir in $places) {
        if (-not $dir) { continue }
        $lnk = $shell.CreateShortcut((Join-Path $dir "$AppName.lnk"))
        $lnk.TargetPath = $exe
        $lnk.WorkingDirectory = $InstallDir
        $lnk.IconLocation = "$ico,0"
        $lnk.Description = "$AppName - criado por Jemerson Barros"
        $lnk.Save()
    }
    Write-Host (T '-- atalhos criados na Area de Trabalho e no Menu Iniciar' '-- shortcuts created on the Desktop and in the Start Menu')
}

Write-Host ''
Write-Host ("== " + (T 'Pronto' 'Done') + ": $exe")
Write-Host (T "   Seus dados ficam em $env:APPDATA\jpzmapstudio (nao sao apagados ao reinstalar)." "   Your data lives in $env:APPDATA\jpzmapstudio (it is kept when you reinstall).")
Write-Host (T '   A janela usa o Microsoft Edge WebView2 (ja vem no Windows 10/11 atualizado); sem ele, abre no navegador.' '   The window uses Microsoft Edge WebView2 (included in an up-to-date Windows 10/11); without it, the app opens in the browser.')
if (-not $NoLaunch) {
    if ($Resume) { Start-Process -FilePath $exe -WorkingDirectory $InstallDir -ArgumentList '--resume' }
    else { Start-Process -FilePath $exe -WorkingDirectory $InstallDir }
}
exit 0
