# SPDX-License-Identifier: MIT
<#
Prüft die Windows-Starter ohne echtes Docker, ohne echtes Claude Code, ohne echten Browser und ohne Internet:

  1. start\akte.ps1: Syntax unter Windows PowerShell 5.1, UTF-8 mit BOM (sonst zeigt 5.1 Umlaute falsch)
  2. alle .cmd-Dateien: CRLF, keine ungeschützten Klammern in echo innerhalb von ( … )-Blöcken (der Fehler, an
     dem START-AKTE.cmd in 0.1.0 auf jedem Windows scheiterte), Wrapper rufen akte.ps1 auf
  3. Pfade mit Attrappen für docker, claude, uvx und den Browser: nicht entpackt (ps1 und cmd), Docker fehlt,
     Docker aus, Port belegt, Bau scheitert, läuft (inkl. status -Json), agent, demo, stop
  4. Der Einrichtungscode erscheint in keiner Konsole (start, status, status -Json, agent, START-AKTE.cmd); er geht
     nur im Fragment (#code=…) an den Browser. Nach der Einrichtung verschwindet er aus .env, und eine Akte mit Daten
     bekommt keinen neuen.

Die Browser-Attrappe wirkt nur mit AKTE_STARTER_TEST=1; Lauf setzt beides, damit nie ein echter Browser aufgeht.

Lokal:  powershell -NoProfile -ExecutionPolicy Bypass -File .github\scripts\starter-pruefen.ps1
#>
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$PS = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$CmdExe = Join-Path $env:SystemRoot 'System32\cmd.exe'
$Utf8 = New-Object System.Text.UTF8Encoding -ArgumentList $false
try { [Console]::OutputEncoding = $Utf8 } catch { }
$Zeigen = ($env:STARTER_PRUEFEN_ZEIGEN -eq '1')   # 1 = jede Starter-Ausgabe mit anzeigen
$script:Fehler = 0
$script:Geprueft = 0

function Pruefe([string]$Name, [bool]$Ok, [string]$Info = '') {
    $script:Geprueft++
    if ($Ok) {
        Write-Host "ok      $Name"
    } else {
        $script:Fehler++
        Write-Host "FEHLER  $Name" -ForegroundColor Red
        if ($Info) { Write-Host (($Info.TrimEnd() -split "`r?`n" | ForEach-Object { "        $_" }) -join "`n") }
    }
}

function Schreib-Datei([string]$Pfad, [string[]]$Zeilen, [switch]$Crlf) {
    $trenner = "`n"
    if ($Crlf) { $trenner = "`r`n" }
    [IO.File]::WriteAllText($Pfad, (($Zeilen -join $trenner) + $trenner), $Utf8)
}

function Freier-Port {
    $l = New-Object System.Net.Sockets.TcpListener -ArgumentList ([System.Net.IPAddress]::Loopback), 0
    $l.Start()
    $p = $l.LocalEndpoint.Port
    $l.Stop()
    return $p
}

$Leeren = @('AKTE_PORT', 'AKTE_DOCKER', 'AKTE_DOCKER_WARTEN', 'AKTE_MCP_QUELLE', 'AKTE_OHNE_BROWSER', 'AKTE_BROWSER',
    'AKTE_STARTER_TEST', 'ATTRAPPE_DOCKER_AUS', 'ATTRAPPE_AKTE_LAEUFT', 'ATTRAPPE_BAU_FEHLER', 'ATTRAPPE_DATEN')

function Lauf {
    param([string]$Datei, [string]$Argumente, [hashtable]$Umgebung = @{}, [int]$Sekunden = 180)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Datei
    $psi.Arguments = $Argumente
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = $true
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = $Utf8
    $psi.StandardErrorEncoding = $Utf8
    foreach ($k in $Leeren) { if ($psi.EnvironmentVariables.ContainsKey($k)) { $psi.EnvironmentVariables.Remove($k) } }
    # Nie einen echten Browser öffnen: Die Attrappe schreibt die Adresse nur in eine Datei.
    $psi.EnvironmentVariables['AKTE_BROWSER'] = $BrowserAttrappe
    $psi.EnvironmentVariables['AKTE_STARTER_TEST'] = '1'
    $psi.EnvironmentVariables['ATTRAPPE_BROWSER_LOG'] = $BrowserLog
    $psi.EnvironmentVariables['AKTE_PFAD_NICHT_AENDERN'] = '1'
    # Start-Protokoll (die-akte-start.log) im Arbeitsordner statt im echten TEMP
    $psi.EnvironmentVariables['TEMP'] = $Arbeit
    $psi.EnvironmentVariables['TMP'] = $Arbeit
    $psi.EnvironmentVariables['CLAUDE_CONFIG_DIR'] = $ClaudeOrdner
    $psi.EnvironmentVariables['ATTRAPPE_LOG'] = $Protokoll
    foreach ($k in $Umgebung.Keys) { $psi.EnvironmentVariables[$k] = [string]$Umgebung[$k] }
    $p = [System.Diagnostics.Process]::Start($psi)
    $aus = $p.StandardOutput.ReadToEndAsync()
    $err = $p.StandardError.ReadToEndAsync()
    $p.StandardInput.Close()
    if (-not $p.WaitForExit($Sekunden * 1000)) {
        try { $p.Kill() } catch { }
        return [pscustomobject]@{ Code = -99; Text = "Zeitüberschreitung nach $Sekunden s" }
    }
    $p.WaitForExit()
    $text = $aus.Result + "`n" + $err.Result
    if ($Zeigen) { Write-Host "--- $Argumente (Rückgabe $($p.ExitCode))"; Write-Host $text }
    return [pscustomobject]@{ Code = $p.ExitCode; Text = $text }
}

function Starter([string]$Ordner, [string]$Argumente, [hashtable]$Umgebung = @{}) {
    return Lauf $PS ("-NoProfile -ExecutionPolicy Bypass -File `"$Ordner\start\akte.ps1`" " + $Argumente) $Umgebung
}

function Kopie([string]$Name) {
    $ziel = Join-Path $Arbeit $Name
    New-Item -ItemType Directory -Path (Join-Path $ziel 'start') -Force | Out-Null
    Copy-Item (Join-Path $Repo 'compose.yaml') $ziel
    Copy-Item (Join-Path $Repo '.env.example') $ziel
    Copy-Item (Join-Path $Repo 'start\akte.ps1') (Join-Path $ziel 'start')
    Copy-Item (Join-Path $Repo 'start\*.cmd') (Join-Path $ziel 'start')
    return $ziel
}

function Als-Json([string]$Text) {
    try { return ($Text.Trim() | ConvertFrom-Json) } catch { return $null }
}

function Felder($Objekt) {
    if ($null -eq $Objekt) { return '' }
    return (($Objekt.PSObject.Properties | ForEach-Object { $_.Name }) -join ',')
}

function Env-Code([string]$Ordner) {
    # Wert von AKTE_EINRICHTUNGSCODE in .env; $null, wenn die Zeile fehlt.
    $datei = Join-Path $Ordner '.env'
    if (-not (Test-Path $datei)) { return $null }
    $m = [regex]::Match([IO.File]::ReadAllText($datei), '(?m)^AKTE_EINRICHTUNGSCODE=(.*?)\s*$')
    if ($m.Success) { return $m.Groups[1].Value }
    return $null
}

function Setze-Einrichtung([string]$Json) {
    Schreib-Datei $EinrichtungDatei @($Json)
}

function Warte-AufBrowser([string]$Erwartet) {
    # Die Attrappe läuft getrennt (wie ein echter Browser); ihre Zeile kommt kurz nach dem Starter.
    for ($i = 0; $i -lt 40; $i++) {
        if ((Test-Path $BrowserLog) -and ([IO.File]::ReadAllText($BrowserLog).Contains($Erwartet))) { return $true }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

# ─── 1. akte.ps1: Syntax und Kodierung ───────────────────────────────────────────────────────────────────────
$skript = Join-Path $Repo 'start\akte.ps1'
$tokens = $null
$parseFehler = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($skript, [ref]$tokens, [ref]$parseFehler)
Pruefe 'akte.ps1: Syntax (Windows PowerShell 5.1)' ($parseFehler.Count -eq 0) (($parseFehler | ForEach-Object { "$($_.Extent.StartLineNumber): $($_.Message)" }) -join "`n")
# PowerShell nimmt „ “ ” als Anführungszeichen: In "…" beendet ein deutsches „ den Text still (Rest wird zu
# Argumenten). Erkennbar an Texten, die mit " beginnen und mit einem typografischen Zeichen enden (oder umgekehrt).
$typo = [char[]]@(0x201C, 0x201D, 0x201E)
$quoteFunde = @()
foreach ($t in $tokens) {
    if ($t.Kind -notin @('StringExpandable', 'StringLiteral')) { continue }
    $text = $t.Extent.Text
    if ($text.Length -lt 2) { continue }
    $a = $text[0]
    $e = $text[$text.Length - 1]
    if ((($a -eq '"') -and ($typo -contains $e)) -or (($typo -contains $a) -and ($e -eq '"'))) {
        $quoteFunde += "Zeile $($t.Extent.StartLineNumber): $text"
    }
}
Pruefe 'akte.ps1: kein deutsches Anführungszeichen beendet einen "…"-Text' ($quoteFunde.Count -eq 0) ($quoteFunde -join "`n")
$kopf = [IO.File]::ReadAllBytes($skript)[0..2]
Pruefe 'akte.ps1: UTF-8 mit BOM' (($kopf[0] -eq 0xEF) -and ($kopf[1] -eq 0xBB) -and ($kopf[2] -eq 0xBF))
$skriptText = [IO.File]::ReadAllText($skript)
Pruefe 'akte.ps1: AKTE_BROWSER wirkt nur mit AKTE_STARTER_TEST=1' ($skriptText -match '\$env:AKTE_BROWSER -and \$env:AKTE_STARTER_TEST -eq ''1''')
# Die Version steht einmal im Starter; die Prüfungen nehmen sie von dort (für Vorabversionen nur eine Stelle ändern).
$Version = ([regex]::Match($skriptText, "(?m)^\`$AkteVersion = '([^']+)'")).Groups[1].Value
Pruefe "akte.ps1: Version als Konstante (`$AkteVersion = '$Version')" ($Version -match '^\d+\.\d+\.\d+')

# ─── 2. .cmd-Dateien ─────────────────────────────────────────────────────────────────────────────────────────
$cmdDateien = @(Get-ChildItem -Path $Repo -Recurse -File -Include '*.cmd', '*.bat' |
    Where-Object { $_.FullName -notmatch '\\(node_modules|\.git|\.venv)\\' })
Pruefe 'es gibt .cmd-Dateien' ($cmdDateien.Count -ge 3)
foreach ($datei in $cmdDateien) {
    $name = $datei.FullName.Substring($Repo.Length + 1)
    $bytes = [IO.File]::ReadAllBytes($datei.FullName)
    $nurLf = 0
    for ($i = 0; $i -lt $bytes.Length; $i++) { if ($bytes[$i] -eq 10 -and ($i -eq 0 -or $bytes[$i - 1] -ne 13)) { $nurLf++ } }
    Pruefe "${name}: nur CRLF" ($nurLf -eq 0) "$nurLf Zeilen enden nur mit LF (Sprungmarken und Blöcke brechen dann)."

    $tiefe = 0
    $funde = @()
    $nr = 0
    foreach ($zeile in [IO.File]::ReadAllLines($datei.FullName)) {
        $nr++
        $z = $zeile.Trim()
        if ($z -match '^(rem\b|::)') { continue }
        $schliesst = $z -match '^\)'
        if ($schliesst) { $tiefe = [Math]::Max(0, $tiefe - 1) }
        if ($tiefe -gt 0 -and $z -match '^@?echo\b' -and $z -match '(?<!\^)[()]') { $funde += "Zeile ${nr}: $z" }
        if ($z -match '(?<!\^)\(\s*$') { $tiefe++ }
    }
    Pruefe "${name}: keine ungeschützte Klammer in echo innerhalb eines Blocks" ($funde.Count -eq 0) ($funde -join "`n")
}
foreach ($w in @('START-AKTE.cmd', 'STOP-AKTE.cmd', 'AGENT-VERBINDEN.cmd')) {
    $pfad = Join-Path $Repo "start\$w"
    $text = ''
    if (Test-Path $pfad) { $text = [IO.File]::ReadAllText($pfad) }
    Pruefe "start\${w}: ruft akte.ps1 mit -ExecutionPolicy Bypass auf" ($text -match '-ExecutionPolicy Bypass -File "%~dp0akte\.ps1"')
}
$text = [IO.File]::ReadAllText((Join-Path $Repo 'start\START-AKTE.cmd'))
Pruefe 'start\START-AKTE.cmd: ruft start -Fenster auf' ($text -match 'akte\.ps1" start -Fenster')

# ─── 3. Pfade mit Attrappen ──────────────────────────────────────────────────────────────────────────────────
$Arbeit = Join-Path ([IO.Path]::GetTempPath()) ('akte-starter-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $Arbeit | Out-Null
$ClaudeOrdner = Join-Path $Arbeit 'claude-einstellungen'
New-Item -ItemType Directory -Path $ClaudeOrdner | Out-Null
$Protokoll = Join-Path $Arbeit 'aufrufe.log'
$BrowserLog = Join-Path $Arbeit 'browser.log'
$Attrappen = Join-Path $Arbeit 'attrappen'
New-Item -ItemType Directory -Path $Attrappen | Out-Null
$Findstr = Join-Path $env:SystemRoot 'System32\findstr.exe'

Schreib-Datei (Join-Path $Attrappen 'docker.cmd') -Crlf @(
    '@echo off',
    '>>"%ATTRAPPE_LOG%" echo docker %*',
    'if /i "%~1"=="version" goto version',
    'if /i "%~1"=="info" goto version',
    'if /i "%~1"=="ps" goto ps',
    'if /i "%~1"=="stop" exit /b 0',
    'if /i "%~1"=="volume" goto volume',
    'if /i "%~1"=="compose" goto compose',
    'exit /b 0',
    ':version',
    'if "%ATTRAPPE_DOCKER_AUS%"=="1" goto aus',
    'echo 99.0.0-attrappe',
    'exit /b 0',
    ':aus',
    'echo error during connect: Docker Desktop is not running 1>&2',
    'exit /b 1',
    ':ps',
    'if "%ATTRAPPE_DOCKER_AUS%"=="1" exit /b 1',
    'if not "%ATTRAPPE_AKTE_LAEUFT%"=="1" exit /b 0',
    'echo die-akte-api-1',
    'echo die-akte-web-1',
    'echo die-akte-proxy-1',
    'exit /b 0',
    ':volume',
    'if "%ATTRAPPE_DATEN%"=="1" goto volume_da',
    'echo Error response from daemon: get die-akte_akte-daten: no such volume 1>&2',
    'exit /b 1',
    ':volume_da',
    'echo die-akte_akte-daten',
    'exit /b 0',
    ':compose',
    'if "%ATTRAPPE_BAU_FEHLER%"=="1" goto baufehler',
    ('echo %* | "' + $Findstr + '" /c:"akte_token" >nul && goto token'),
    ('echo %* | "' + $Findstr + '" /c:"akte_konten" >nul && goto konten'),
    ('echo %* | "' + $Findstr + '" /c:"akte_demo" >nul && goto demo'),
    'exit /b 0',
    ':baufehler',
    'echo failed to solve: attrappe 1>&2',
    'exit /b 1',
    ':token',
    'echo ATTRAPPExTOKENxATTRAPPExTOKENxATTRAPPExx',
    'exit /b 0',
    ':konten',
    'echo KONTO:testkonto',
    'exit /b 0',
    ':demo',
    'echo No hostname was supplied. Reverting to default localhost',
    'echo Demo-Akte angelegt: /akte/demo-musterhafen',
    'exit /b 0'
)
Schreib-Datei (Join-Path $Attrappen 'claude.cmd') -Crlf @(
    '@echo off',
    '>>"%ATTRAPPE_LOG%" echo claude %*',
    'if /i "%~2"=="remove" exit /b 1',
    'exit /b 0'
)
Schreib-Datei (Join-Path $Attrappen 'uvx.cmd') -Crlf @(
    '@echo off',
    '>>"%ATTRAPPE_LOG%" echo uvx %*',
    'echo usage: akte [-h]',
    'exit /b 0'
)
Schreib-Datei (Join-Path $Attrappen 'browser.cmd') -Crlf @(
    '@echo off',
    '>>"%ATTRAPPE_BROWSER_LOG%" echo %*',
    'exit /b 0'
)
$DockerAttrappe = Join-Path $Attrappen 'docker.cmd'
$BrowserAttrappe = Join-Path $Attrappen 'browser.cmd'

# Antwortet wie die Akte auf GET /api/v1/auth/einrichtung/ (Antwort = Inhalt der Datei einrichtung.json).
$EinrichtungDatei = Join-Path $Arbeit 'einrichtung.json'
Setze-Einrichtung '{"offen": true, "grund": "offen"}'
$ServerSkript = Join-Path $Arbeit 'akte-attrappe.ps1'
Schreib-Datei $ServerSkript @(
    'param([int]$Port, [string]$Datei)',
    '$l = New-Object System.Net.Sockets.TcpListener -ArgumentList ([System.Net.IPAddress]::Loopback), $Port',
    '$l.Start()',
    'while ($true) {',
    '    $c = $l.AcceptTcpClient()',
    '    try {',
    '        $s = $c.GetStream()',
    '        $r = New-Object System.IO.StreamReader -ArgumentList $s',
    '        $zeile = $r.ReadLine()',
    '        while ($true) { $h = $r.ReadLine(); if ($null -eq $h -or $h -eq '''') { break } }',
    '        if ($zeile -match '' /api/v1/auth/einrichtung/ '') { $body = ([IO.File]::ReadAllText($Datei)).Trim(); $st = ''200 OK'' }',
    '        else { $body = ''{}''; $st = ''404 Not Found'' }',
    '        $b = [Text.Encoding]::UTF8.GetBytes($body)',
    '        $k = [Text.Encoding]::ASCII.GetBytes("HTTP/1.1 $st`r`nContent-Type: application/json`r`nContent-Length: $($b.Length)`r`nConnection: close`r`n`r`n")',
    '        $s.Write($k, 0, $k.Length); $s.Write($b, 0, $b.Length); $s.Flush()',
    '    } catch { } finally { $c.Close() }',
    '}'
)
$Port = Freier-Port
$server = Start-Process -FilePath $PS -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$ServerSkript`"", '-Port', $Port, '-Datei', "`"$EinrichtungDatei`"") -PassThru -WindowStyle Hidden
$bereit = $false
for ($i = 0; $i -lt 40 -and -not $bereit; $i++) {
    Start-Sleep -Milliseconds 250
    try { $t = New-Object System.Net.Sockets.TcpClient; $t.Connect('127.0.0.1', $Port); $t.Close(); $bereit = $true } catch { }
}
Pruefe 'Akte-Attrappe (HTTP) läuft' $bereit

$Vertrag = 'docker,akte,url,einrichtung_offen,einrichtung_grund,agent_verbunden'

try {
    $ohneDocker = @{ AKTE_DOCKER = (Join-Path $Arbeit 'gibt-es-nicht\docker.exe') }
    $mitDocker = @{ AKTE_DOCKER = $DockerAttrappe; ATTRAPPE_AKTE_LAEUFT = '1'; AKTE_PORT = "$Port" }
    $mitDaten = $mitDocker.Clone()
    $mitDaten['ATTRAPPE_DATEN'] = '1'

    # nicht entpackt: akte.ps1 ohne compose.yaml daneben
    $einzeln = Join-Path $Arbeit 'nur-skript'
    New-Item -ItemType Directory -Path (Join-Path $einzeln 'start') -Force | Out-Null
    Copy-Item $skript (Join-Path $einzeln 'start')
    $r = Starter $einzeln 'start -Still'
    Pruefe 'nicht entpackt (akte.ps1): Rückgabe 2 und Hinweis' (($r.Code -eq 2) -and ($r.Text -match 'zuerst entpacken')) "Code $($r.Code)`n$($r.Text)"

    # nicht entpackt: START-AKTE.cmd allein (so entpackt der Explorer beim Start aus der ZIP)
    $nurCmd = Join-Path $Arbeit 'nur-cmd'
    New-Item -ItemType Directory -Path $nurCmd | Out-Null
    Copy-Item (Join-Path $Repo 'start\START-AKTE.cmd') $nurCmd
    $r = Lauf $CmdExe ('/d /s /c ""' + (Join-Path $nurCmd 'START-AKTE.cmd') + '""')
    Pruefe 'nicht entpackt (START-AKTE.cmd allein): Rückgabe 2 und Hinweis' (($r.Code -eq 2) -and ($r.Text -match 'zuerst entpacken')) "Code $($r.Code)`n$($r.Text)"

    # Docker fehlt
    $ordner = Kopie 'docker-fehlt'
    $r = Starter $ordner 'start -Still' $ohneDocker
    Pruefe 'Docker fehlt: Rückgabe 3, winget-Zeile, All-users' (($r.Code -eq 3) -and ($r.Text -match 'winget install -e --id Docker\.DockerDesktop') -and ($r.Text -match 'All-users')) "Code $($r.Code)`n$($r.Text)"
    Pruefe 'Docker fehlt: Umlaute kommen als UTF-8 an' ($r.Text -match 'läuft in Docker') $r.Text
    $r = Lauf $CmdExe ('/d /s /c ""' + (Join-Path $ordner 'start\START-AKTE.cmd') + '" -Still"') $ohneDocker
    Pruefe 'Docker fehlt über START-AKTE.cmd -Still: Rückgabe 3 ohne Warten' ($r.Code -eq 3) "Code $($r.Code)`n$($r.Text)"
    $r = Starter $ordner 'status -Json' $ohneDocker
    $j = Als-Json $r.Text
    Pruefe 'Docker fehlt: status -Json ist gültiges JSON' ($null -ne $j) $r.Text
    Pruefe 'status -Json: genau die Felder aus dem Vertrag (ohne Einrichtungscode)' ((Felder $j) -eq $Vertrag) (Felder $j)
    if ($j) {
        Pruefe 'Docker fehlt: docker=fehlt, akte=aus, grund=null' (($j.docker -eq 'fehlt') -and ($j.akte -eq 'aus') -and ($j.einrichtung_offen -eq $false) -and ($null -eq $j.einrichtung_grund) -and ($j.agent_verbunden -eq $false)) $r.Text
    }

    # Docker aus und startet nicht (kurze Wartezeit)
    $ordner = Kopie 'docker-aus'
    $r = Starter $ordner 'start -Still' @{ AKTE_DOCKER = $DockerAttrappe; ATTRAPPE_DOCKER_AUS = '1'; AKTE_DOCKER_WARTEN = '4' }
    Pruefe 'Docker aus: Rückgabe 4 und Hinweis' (($r.Code -eq 4) -and ($r.Text -match 'Docker startet nicht')) "Code $($r.Code)`n$($r.Text)"
    $r = Starter $ordner 'status -Json' @{ AKTE_DOCKER = $DockerAttrappe; ATTRAPPE_DOCKER_AUS = '1' }
    $j = Als-Json $r.Text
    Pruefe 'Docker aus: status -Json docker=aus' (($null -ne $j) -and ($j.docker -eq 'aus')) $r.Text

    # Port belegt von einem fremden Programm (die Attrappe hält den Port, die Akte-Container laufen nicht)
    $ordner = Kopie 'port-belegt'
    $r = Starter $ordner 'start -Still' @{ AKTE_DOCKER = $DockerAttrappe; AKTE_PORT = "$Port" }
    Pruefe 'Port belegt (AKTE_PORT fest): Rückgabe 5 und Hinweis' (($r.Code -eq 5) -and ($r.Text -match 'belegt')) "Code $($r.Code)`n$($r.Text)"

    # Bau scheitert
    $ordner = Kopie 'bau-fehler'
    $r = Starter $ordner 'start -Still' @{ AKTE_DOCKER = $DockerAttrappe; ATTRAPPE_BAU_FEHLER = '1'; AKTE_PORT = "$(Freier-Port)" }
    Pruefe 'Bau scheitert: Rückgabe 6, Docker-Meldung sichtbar' (($r.Code -eq 6) -and ($r.Text -match 'Start fehlgeschlagen') -and ($r.Text -match 'failed to solve')) "Code $($r.Code)`n$($r.Text)"

    # ── Läuft, erstes Konto fehlt: Code entsteht, geht nur an den Browser ──
    $ordner = Kopie 'laeuft'
    Setze-Einrichtung '{"offen": true, "grund": "offen"}'
    if (Test-Path $BrowserLog) { Remove-Item $BrowserLog }
    $r = Starter $ordner 'start -Still' $mitDocker
    $envText = ''
    if (Test-Path (Join-Path $ordner '.env')) { $envText = [IO.File]::ReadAllText((Join-Path $ordner '.env')) }
    $code = [string](Env-Code $ordner)
    $anzeige = ''
    if ($code.Length -eq 8) { $anzeige = $code.Substring(0, 4) + '-' + $code.Substring(4) }
    Pruefe 'läuft: Rückgabe 0' ($r.Code -eq 0) "Code $($r.Code)`n$($r.Text)"
    Pruefe 'läuft: .env mit geheimem Schlüssel' ($envText -match '(?m)^DJANGO_SECRET_KEY=[A-Za-z0-9_-]{50,}\s*$') $envText
    Pruefe 'läuft: Einrichtungscode 8 Zeichen ohne Verwechsler (neue Akte ohne Daten)' ($code -match '^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{8}$') $code
    Pruefe 'läuft: Ausgabe nennt den Einrichtungscode nicht' ($anzeige -and -not $r.Text.Contains($anzeige) -and -not $r.Text.Contains($code)) $r.Text
    Pruefe 'läuft: Ausgabe sagt „Der Browser ist offen“ und nennt /akte/einrichten' ($r.Text.Contains('Der Browser ist offen: wähl dort Name und Passwort.') -and ($r.Text -match "localhost:$Port/akte/einrichten")) $r.Text
    $erwartet = "http://localhost:$Port/akte/einrichten#code=$anzeige"
    $imBrowser = Warte-AufBrowser $erwartet
    $browserText = ''
    if (Test-Path $BrowserLog) { $browserText = [IO.File]::ReadAllText($BrowserLog) }
    Pruefe 'läuft: Browser bekommt den Code im Fragment (#code=)' $imBrowser "erwartet: $erwartet`nbekommen: $browserText"
    Pruefe 'läuft: docker compose up -d --build --wait aufgerufen' ([IO.File]::ReadAllText($Protokoll) -match 'docker compose up -d --build --wait') ''
    Pruefe 'läuft: .env ohne BOM' ([IO.File]::ReadAllBytes((Join-Path $ordner '.env'))[0] -ne 0xEF) ''
    $acl = Get-Acl -LiteralPath (Join-Path $ordner '.env')
    $ich = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $regeln = @($acl.Access)
    $nurIch = ($regeln.Count -eq 1) -and ($regeln[0].IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value -eq $ich)
    Pruefe 'läuft: .env nur für das eigene Konto (keine geerbten Rechte)' ($acl.AreAccessRulesProtected -and $nurIch) (($regeln | ForEach-Object { "$($_.IdentityReference) $($_.FileSystemRights)" }) -join "`n")
    # Wie auf dem GitHub-Rechner: Erbt der Ordner nichts, hat .env feste Einträge für SYSTEM und Administratoren.
    # Der nächste Start muss sie entfernen, nicht nur die Vererbung abschalten.
    $envPfad = Join-Path $ordner '.env'
    $fremd = New-Object System.Security.AccessControl.FileSecurity
    $fremd.SetSecurityDescriptorSddlForm("D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;$ich)", [System.Security.AccessControl.AccessControlSections]::Access)
    (New-Object System.IO.FileInfo $envPfad).SetAccessControl($fremd)
    $r2 = Starter $ordner 'start -Still' $mitDaten
    $envText2 = [IO.File]::ReadAllText($envPfad)
    Pruefe 'zweiter Start (Einrichtung noch offen): Schlüssel und Code bleiben' (($r2.Code -eq 0) -and ($envText2 -eq $envText)) "Code $($r2.Code)"
    $acl = Get-Acl -LiteralPath $envPfad
    $regeln = @($acl.Access)
    $nurIch = ($regeln.Count -eq 1) -and ($regeln[0].IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value -eq $ich)
    Pruefe 'zweiter Start: feste Einträge für SYSTEM und Administratoren aus .env entfernt' ($acl.AreAccessRulesProtected -and $nurIch) (($regeln | ForEach-Object { "$($_.IdentityReference) $($_.FileSystemRights)" }) -join "`n")

    # Der Doppelklick-Weg (START-AKTE.cmd, -Fenster): öffnet den Browser wie start, zeigt keinen Code.
    if (Test-Path $BrowserLog) { Remove-Item $BrowserLog }
    $r = Lauf $CmdExe ('/d /s /c ""' + (Join-Path $ordner 'start\START-AKTE.cmd') + '""') $mitDaten
    Pruefe 'START-AKTE.cmd (-Fenster): Rückgabe 0, kein Code in der Ausgabe' (($r.Code -eq 0) -and $anzeige -and -not $r.Text.Contains($anzeige) -and -not $r.Text.Contains($code)) "Code $($r.Code)`n$($r.Text)"
    Pruefe 'START-AKTE.cmd (-Fenster): Browser bekommt den Code im Fragment' (Warte-AufBrowser $erwartet) ''

    # Ohne Browser: Notweg akte_einrichten (braucht keinen Code), Code nicht ausgeben
    $ohneBrowser = $mitDaten.Clone()
    $ohneBrowser['AKTE_OHNE_BROWSER'] = '1'
    $r = Starter $ordner 'start -Still' $ohneBrowser
    Pruefe 'ohne Browser: Notweg akte_einrichten, kein Code' (($r.Code -eq 0) -and ($r.Text -match 'manage\.py akte_einrichten') -and -not $r.Text.Contains($anzeige)) $r.Text

    $r = Starter $ordner 'status -Json' $mitDocker
    $j = Als-Json $r.Text
    Pruefe 'läuft: status -Json gültig, genau die Felder aus dem Vertrag' ((Felder $j) -eq $Vertrag) $r.Text
    if ($j) {
        Pruefe 'läuft: status -Json Werte (offen, grund=offen, Adresse ohne Code)' (($j.docker -eq 'laeuft') -and ($j.akte -eq 'laeuft') -and ($j.einrichtung_offen -eq $true) -and ($j.einrichtung_grund -eq 'offen') -and ($j.url -eq "http://localhost:$Port/akte/einrichten") -and ($j.agent_verbunden -eq $false)) $r.Text
    }
    Pruefe 'läuft: status -Json nennt den Code nicht' (-not $r.Text.Contains($anzeige) -and -not $r.Text.Contains($code)) $r.Text
    $r = Starter $ordner 'status' $mitDocker
    Pruefe 'läuft: status (Text) nennt den Code nicht' (($r.Code -eq 0) -and ($r.Text -match 'fehlt noch') -and -not $r.Text.Contains($anzeige)) $r.Text

    # agent, solange das erste Konto fehlt
    $mitAgent = $mitDaten.Clone()
    $mitAgent['PATH'] = $Attrappen + ';' + $env:Path
    $r = Starter $ordner 'agent -Still' $mitAgent
    Pruefe 'agent ohne Konto: Rückgabe 9, Hinweis auf /akte/einrichten, kein Code' (($r.Code -eq 9) -and ($r.Text -match 'akte/einrichten') -and -not $r.Text.Contains($anzeige)) "Code $($r.Code)`n$($r.Text)"

    # Ältere Akte ohne „grund“ in der Antwort: wird abgeleitet
    Setze-Einrichtung '{"offen": true}'
    $j = Als-Json (Starter $ordner 'status -Json' $mitDocker).Text
    Pruefe 'status -Json ohne „grund“ vom Server: grund=offen abgeleitet' (($null -ne $j) -and ($j.einrichtung_grund -eq 'offen')) (Felder $j)

    # ── Der Mensch hat das Konto angelegt: Code verschwindet aus .env ──
    Setze-Einrichtung '{"offen": false, "grund": "eingerichtet"}'
    [IO.File]::WriteAllText($Protokoll, '')
    $r = Starter $ordner 'agent -Still' $mitAgent
    $aufrufe = [IO.File]::ReadAllText($Protokoll)
    Pruefe 'agent: Rückgabe 0 und Schlusssatz' (($r.Code -eq 0) -and $r.Text.Contains('Fertig. Beende Claude (/exit) und starte es neu mit: claude --continue')) "Code $($r.Code)`n$($r.Text)"
    Pruefe 'agent: Token erscheint nie in der Ausgabe' (-not $r.Text.Contains('ATTRAPPExTOKENxATTRAPPExTOKENxATTRAPPExx')) $r.Text
    $quelle = "https://github.com/ThePyth0nKid/ultra-akte/archive/refs/tags/v$Version.zip#subdirectory=mcp"
    $erwartetMcp = "claude mcp add --scope user akte -e AKTE_BASIS=http://127.0.0.1:$Port -e AKTE_TOKEN=ATTRAPPExTOKENxATTRAPPExTOKENxATTRAPPExx -- uvx --python 3.12 --from $quelle akte-mcp"
    Pruefe 'agent: claude mcp add wie im Vertrag' ($aufrufe.Contains($erwartetMcp)) $aufrufe
    Pruefe 'agent: alter Eintrag wird vorher entfernt' ($aufrufe.Contains('claude mcp remove akte -s user')) $aufrufe
    Pruefe 'agent: vorwärmen mit dem Server selbst (Python 3.12)' ($aufrufe.Contains("uvx --python 3.12 --from $quelle akte-mcp --selbsttest")) $aufrufe
    Pruefe 'agent: Konto-Suche über akte_konten (Redaktion oder Superuser)' ($aufrufe -match 'manage\.py akte_konten') $aufrufe
    Pruefe 'agent: Token für das einzige Redaktionskonto' ($aufrufe -match 'akte_token testkonto') $aufrufe
    Pruefe 'agent nach der Einrichtung: Code aus .env gelöscht' (([string](Env-Code $ordner)) -eq '') ([IO.File]::ReadAllText((Join-Path $ordner '.env')))

    # Neuer Start einer eingerichteten Akte mit Daten: kein neuer Code
    $r = Starter $ordner 'start -Still' $mitDaten
    Pruefe 'Start nach der Einrichtung: kein neuer Code in .env' (($r.Code -eq 0) -and (([string](Env-Code $ordner)) -eq '')) "Code $($r.Code)`n$($r.Text)"

    # start löscht den Code ebenso (falls agent nie lief)
    $ordner2 = Kopie 'eingerichtet'
    Setze-Einrichtung '{"offen": true, "grund": "offen"}'
    [void](Starter $ordner2 'start -Still' $mitDocker)
    $vorher = [string](Env-Code $ordner2)
    Setze-Einrichtung '{"offen": false, "grund": "eingerichtet"}'
    $r = Starter $ordner2 'start -Still' $mitDaten
    Pruefe 'start nach der Einrichtung: Code aus .env gelöscht, Hinweis' (($vorher.Length -eq 8) -and (([string](Env-Code $ordner2)) -eq '') -and ($r.Text -match 'aus \.env gelöscht')) "vorher $vorher`n$($r.Text)"

    # Neue Version einer eingerichteten Akte (alte .env ohne Code, Volume mit Daten): kein Code
    $ordner3 = Kopie 'neue-version'
    Schreib-Datei (Join-Path $ordner3 '.env') @('DJANGO_SECRET_KEY=altaltaltaltaltaltaltaltaltaltaltaltaltaltaltaltaltalt', 'AKTE_PORT=8080')
    $r = Starter $ordner3 'start -Still' $mitDaten
    Pruefe 'neue Version mit Daten: kein Einrichtungscode angelegt' (($r.Code -eq 0) -and ($null -eq (Env-Code $ordner3))) ([IO.File]::ReadAllText((Join-Path $ordner3 '.env')))

    # Daten, aber kein Konto und kein Code: Notweg im Terminal
    Setze-Einrichtung '{"offen": false, "grund": "kein_code"}'
    $r = Starter $ordner3 'start -Still' $mitDaten
    Pruefe 'kein Code, kein Konto: Notweg akte_einrichten' (($r.Code -eq 0) -and ($r.Text -match 'manage\.py akte_einrichten')) $r.Text
    $j = Als-Json (Starter $ordner3 'status -Json' $mitDocker).Text
    Pruefe 'kein Code: status -Json grund=kein_code' (($null -ne $j) -and ($j.einrichtung_offen -eq $false) -and ($j.einrichtung_grund -eq 'kein_code')) (Felder $j)

    # agent_verbunden aus .claude.json (mit Schlüsseln, die sich nur in der Groß-/Kleinschreibung unterscheiden)
    Setze-Einrichtung '{"offen": false, "grund": "eingerichtet"}'
    Schreib-Datei (Join-Path $ClaudeOrdner '.claude.json') @(
        '{"projects": {"C:/x": {}, "c:/X": {}},',
        ' "mcpServers": {"akte": {"type": "stdio", "command": "uvx", "args": ["akte-mcp"],',
        "  `"env`": {`"AKTE_BASIS`": `"http://127.0.0.1:$Port`", `"AKTE_TOKEN`": `"x`"}}}}"
    )
    $r = Starter $ordner 'status -Json' $mitDocker
    $j = Als-Json $r.Text
    Pruefe 'status -Json: agent_verbunden erkennt den Eintrag' (($null -ne $j) -and ($j.agent_verbunden -eq $true) -and ($j.einrichtung_offen -eq $false) -and ($j.einrichtung_grund -eq 'eingerichtet') -and ($j.url -eq "http://localhost:$Port/akte")) $r.Text

    # -Json: immer JSON, auch bei Fehlern (CR9)
    $r = Starter $ordner 'start -Json' $mitDocker
    $j = Als-Json $r.Text
    Pruefe '-Json bei start: JSON-Fehlerobjekt, Rückgabe 1' (($r.Code -eq 1) -and ($null -ne $j) -and $j.fehler) $r.Text
    $kaputt = Kopie 'json-fehler'
    New-Item -ItemType Directory -Path (Join-Path $kaputt '.env') | Out-Null   # .env als Ordner: Lesen wirft
    $r = Starter $kaputt 'status -Json' @{ AKTE_DOCKER = $DockerAttrappe; ATTRAPPE_AKTE_LAEUFT = '1' }   # Port aus .env
    $j = Als-Json $r.Text
    Pruefe 'status -Json bei einer Ausnahme: JSON-Fehlerobjekt, Rückgabe 1' (($r.Code -eq 1) -and ($null -ne $j) -and ([string]$j.fehler -match 'Unerwarteter Fehler')) "Code $($r.Code)`n$($r.Text)"

    # demo und stop
    $r = Starter $ordner 'demo -Still' $mitDocker
    Pruefe 'demo: Rückgabe 0 und Adresse der Demo-Wand' (($r.Code -eq 0) -and ($r.Text -match "localhost:$Port/akte/demo-musterhafen")) "Code $($r.Code)`n$($r.Text)"
    $r = Starter $ordner 'stop -Still' $mitDocker
    Pruefe 'stop: Rückgabe 0' (($r.Code -eq 0) -and ($r.Text -match 'angehalten')) "Code $($r.Code)`n$($r.Text)"

    # demo, wenn die Akte nicht läuft
    $r = Starter $ordner 'demo -Still' @{ AKTE_DOCKER = $DockerAttrappe; AKTE_PORT = "$Port" }
    Pruefe 'demo ohne laufende Akte: Rückgabe 10' ($r.Code -eq 10) "Code $($r.Code)`n$($r.Text)"
} finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
    Start-Sleep -Milliseconds 300
    Remove-Item -Recurse -Force $Arbeit -ErrorAction SilentlyContinue
}

Write-Host ''
if ($script:Fehler -gt 0) {
    Write-Host "$($script:Fehler) von $($script:Geprueft) Prüfungen fehlgeschlagen." -ForegroundColor Red
    exit 1
}
Write-Host "Alle $($script:Geprueft) Prüfungen bestanden." -ForegroundColor Green
exit 0
