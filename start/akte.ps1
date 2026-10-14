# SPDX-License-Identifier: AGPL-3.0-or-later
<#
Die Akte – Starter für Windows (läuft mit Windows PowerShell 5.1, ohne Zusatzprogramme).

  akte.ps1 start     Docker prüfen und starten, Akte bauen und starten, Browser öffnen (Standard)
  akte.ps1 stop      Akte anhalten; die Daten bleiben
  akte.ps1 status    Zustand anzeigen; mit -Json als eine Zeile JSON für Agenten
  akte.ps1 agent     Claude Code mit der Akte verbinden (uv, Token, claude mcp add)
  akte.ps1 demo      Erfundene Demo-Akte „Freie Stadt Musterhafen“ laden

Schalter: -Still (keine Rückfragen, kein Warten auf Enter; für Agenten) · -Json (nur bei status) · -Konto NAME (bei
agent) · -OhneBrowser · -Fenster (setzen nur die .cmd-Dateien: am Ende auf Enter warten, damit das Fenster offen
bleibt; nur, wenn Ein- und Ausgabe ein echtes Konsolenfenster sind).

Der Einrichtungscode für das erste Konto steht in keiner Konsole, auch nicht im Fenster nach einem Doppelklick.
start öffnet den Browser selbst, mit dem Code im Fragment der Adresse (#code=…; ein Fragment schickt der Browser an
keinen Server), und die Seite trägt ihn ein. Geht kein Browser auf, bleibt der Notweg im Terminal (akte_einrichten
fragt Name und Passwort und braucht keinen Code). Nach der Einrichtung löscht der Starter den Code aus .env. Eine
Akte, die schon Daten hat, bekommt keinen neuen.

Aufruf ohne Doppelklick (Windows lässt .ps1-Dateien sonst nicht laufen):
  powershell -NoProfile -ExecutionPolicy Bypass -File start\akte.ps1 start -Still

Rückgabewerte: 0 fertig · 1 unerwarteter Fehler · 2 nicht entpackt · 3 Docker fehlt · 4 Docker läuft nicht ·
5 Port belegt · 6 Bau, Start oder Befehl fehlgeschlagen · 7 Claude Code fehlt · 8 uv fehlt · 9 erstes Konto fehlt
oder Konto unklar · 10 Akte läuft nicht · 11 Akte-Baustein für den Agenten lädt nicht · 12 Token fehlt ·
13 claude mcp add fehlgeschlagen

Umgebungsvariablen für Sonderfälle und Tests: AKTE_PORT (gewinnt wie bei docker compose über .env),
AKTE_DOCKER (Pfad zu docker; dann startet der Starter Docker Desktop nicht selbst), AKTE_DOCKER_WARTEN (Sekunden,
Standard 180), AKTE_MCP_QUELLE (eigene Quelle für akte-mcp statt der Release-ZIP), AKTE_OHNE_BROWSER=1,
AKTE_PFAD_NICHT_AENDERN=1 (Benutzer-Pfad nicht anfassen). Nur für die Prüfskripte: AKTE_BROWSER (Programm statt des
Standard-Browsers) wirkt nur zusammen mit AKTE_STARTER_TEST=1.
#>
param(
    [Parameter(Position = 0)][string]$Befehl = 'start',
    [switch]$Still,
    [switch]$Json,
    [string]$Konto = '',
    [switch]$OhneBrowser,
    [switch]$Fenster
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# Gleiche Schreibweisen wie bei akte.sh zulassen (--still, --json …).
foreach ($weiteres in $args) {
    switch -Regex ($weiteres) {
        '^--?still$' { $Still = $true; continue }
        '^--?json$' { $Json = $true; continue }
        '^--?ohne-?browser$' { $OhneBrowser = $true; continue }
        default { }
    }
}

$AkteVersion = '0.2.0'
$McpQuelle = "https://github.com/ThePyth0nKid/die-akte/archive/refs/tags/v$AkteVersion.zip#subdirectory=mcp"
if ($env:AKTE_MCP_QUELLE) { $McpQuelle = $env:AKTE_MCP_QUELLE }
# uv lädt den Akte-Baustein für Claude. Feste Version des offiziellen Installers; die geladene Datei muss genau diese
# Prüfsumme haben, sonst läuft sie nicht (neue Version: Datei laden, Get-FileHash, beide Werte hier und in akte.sh).
$UvVersion = '0.12.21'
$UvInstallerUrl = "https://astral.sh/uv/$UvVersion/install.ps1"
$UvInstallerSha256 = '47385decce28406617801b01da9e8dd05b278fcd6d6f4adeec0c007b8312bad3'
# Name des Daten-Volumes (Projekt „die-akte“ aus compose.yaml). Gibt es das, lief diese Akte schon einmal.
$DatenVolume = 'die-akte_akte-daten'

# ─── Ausgabe: immer UTF-8, damit Umlaute auch bei Agenten (umgeleitete Ausgabe) ankommen ──────────────────────
$Utf8 = New-Object System.Text.UTF8Encoding -ArgumentList $false
$script:Aus = $null
try {
    if ([Console]::IsOutputRedirected) {
        $script:Aus = New-Object System.IO.StreamWriter -ArgumentList ([Console]::OpenStandardOutput()), $Utf8
        $script:Aus.AutoFlush = $true
    }
} catch { $script:Aus = $null }
try { [Console]::OutputEncoding = $Utf8 } catch { }
$OutputEncoding = $Utf8

function Schreib {
    param([string]$Text = '', [string]$Farbe = '')
    if ($Json) { return }
    if ($script:Aus) { $script:Aus.WriteLine($Text); return }
    if ($Farbe) { Write-Host $Text -ForegroundColor $Farbe } else { Write-Host $Text }
}

function SchreibRoh([string]$Text) {
    if ($script:Aus) { $script:Aus.WriteLine($Text) } else { [Console]::Out.WriteLine($Text) }
}

function SchreibJsonFehler([string]$Text) {
    SchreibRoh (@{ fehler = $Text } | ConvertTo-Json -Compress)
}

function Echtes-Fenster {
    # Nur dann auf Enter warten: Die .cmd-Datei hat -Fenster gesetzt, kein -Still/-Json, und Eingabe UND Ausgabe sind
    # ein echtes Konsolenfenster. Ruft ein Agent auf (umgeleitet), blockiert der Starter nie.
    if (-not $Fenster -or $Still -or $Json) { return $false }
    $umgeleitet = $true
    try { $umgeleitet = ([Console]::IsInputRedirected -or [Console]::IsOutputRedirected) } catch { }
    return (-not $umgeleitet)
}

function Ende([int]$Code) {
    if (Echtes-Fenster) {
        Write-Host ''
        [void](Read-Host 'Drück Enter, um dieses Fenster zu schließen')
    }
    if ($script:Aus) { try { $script:Aus.Flush() } catch { } }
    exit $Code
}

# ─── Orte ────────────────────────────────────────────────────────────────────────────────────────────────────
$StartOrdner = (Get-Location).ProviderPath
$Wurzel = Split-Path -Parent $PSScriptRoot
$EnvDatei = Join-Path $Wurzel '.env'
$SkriptPfad = $PSCommandPath
$AgentAufruf = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$SkriptPfad`""
$script:Docker = $null

# ─── Werkzeuge ───────────────────────────────────────────────────────────────────────────────────────────────
function ConvertTo-Argument([string]$Wert) {
    # Windows-Regeln für eine Befehlszeile (CommandLineToArgvW): nur quoten, wenn nötig.
    if ($Wert -eq '') { return '""' }
    if ($Wert -notmatch '[\s"]') { return $Wert }
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    $schraeg = 0
    foreach ($z in $Wert.ToCharArray()) {
        if ($z -eq '\') { $schraeg++; continue }
        if ($z -eq '"') { [void]$sb.Append('\' * ($schraeg * 2 + 1)); [void]$sb.Append('"') }
        else { [void]$sb.Append('\' * $schraeg); [void]$sb.Append($z) }
        $schraeg = 0
    }
    [void]$sb.Append('\' * ($schraeg * 2))
    [void]$sb.Append('"')
    return $sb.ToString()
}

function Invoke-Nativ {
    # Startet ein Programm, sammelt Ausgabe und Fehlerausgabe (UTF-8) und gibt beides mit dem Rückgabewert zurück.
    param(
        [string]$Datei,
        [string[]]$Argumente = @(),
        [int]$Sekunden = 120,
        [string]$Ordner = '',
        [scriptblock]$Fortschritt = $null,
        [string[]]$OhneVariablen = @()
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Datei
    $psi.Arguments = (@($Argumente | ForEach-Object { ConvertTo-Argument $_ }) -join ' ')
    $psi.UseShellExecute = $false
    foreach ($v in $OhneVariablen) { if ($psi.EnvironmentVariables.ContainsKey($v)) { $psi.EnvironmentVariables.Remove($v) } }
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = $true
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = $Utf8
    $psi.StandardErrorEncoding = $Utf8
    if ($Ordner) { $psi.WorkingDirectory = $Ordner }
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    try { [void]$p.Start() }
    catch { return [pscustomobject]@{ Code = -1; Aus = ''; Fehler = $_.Exception.Message } }
    $ausAufgabe = $p.StandardOutput.ReadToEndAsync()
    $fehlerAufgabe = $p.StandardError.ReadToEndAsync()
    $p.StandardInput.Close()
    $gewartet = 0
    while (-not $p.WaitForExit(5000)) {
        $gewartet += 5
        if ($Fortschritt) { & $Fortschritt $gewartet }
        if ($gewartet -ge $Sekunden) {
            try { $p.Kill() } catch { }
            return [pscustomobject]@{ Code = -1; Aus = ''; Fehler = "Zeitüberschreitung nach $Sekunden Sekunden." }
        }
    }
    $p.WaitForExit()
    return [pscustomobject]@{ Code = $p.ExitCode; Aus = $ausAufgabe.Result; Fehler = $fehlerAufgabe.Result }
}

function Schreib-Schluss($Ergebnis, [int]$Zeilen = 20, [string]$Verdecken = '') {
    $text = ([string]$Ergebnis.Aus + "`n" + [string]$Ergebnis.Fehler)
    if ($Verdecken) { $text = $text.Replace($Verdecken, '***') }
    $alle = @($text -split "`r?`n" | Where-Object { $_.Trim() })
    foreach ($z in ($alle | Select-Object -Last $Zeilen)) { Schreib "  $z" }
}

function Finde-Programm([string]$Name, [string[]]$Weitere = @()) {
    $treffer = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($treffer) { return $treffer.Path }
    foreach ($w in $Weitere) { if ($w -and (Test-Path -LiteralPath $w)) { return $w } }
    return $null
}

function Http-Hole([string]$Url, [int]$Ms = 5000) {
    $antwort = $null
    try {
        $anfrage = [System.Net.HttpWebRequest]::Create($Url)
        $anfrage.Proxy = $null
        $anfrage.Timeout = $Ms
        $anfrage.ReadWriteTimeout = $Ms
        $anfrage.Accept = 'application/json'
        $antwort = $anfrage.GetResponse()
    } catch {
        $ex = $_.Exception
        while ($ex -and -not ($ex -is [System.Net.WebException])) { $ex = $ex.InnerException }
        if ($ex -and $ex.Response) { $antwort = $ex.Response } else { return $null }
    }
    try {
        $leser = New-Object System.IO.StreamReader -ArgumentList $antwort.GetResponseStream(), $Utf8
        $text = $leser.ReadToEnd()
        $leser.Close()
        return [pscustomobject]@{ Code = [int]$antwort.StatusCode; Text = $text }
    } catch {
        return $null
    } finally {
        $antwort.Close()
    }
}

# ─── .env ────────────────────────────────────────────────────────────────────────────────────────────────────
function Env-Wert([string]$Name) {
    if (-not (Test-Path -LiteralPath $EnvDatei)) { return '' }
    foreach ($z in [IO.File]::ReadAllLines($EnvDatei, $Utf8)) {
        if ($z -match ('^\s*' + [regex]::Escape($Name) + '\s*=(.*)$')) {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return ''
}

function Setze-EnvWert([string]$Name, [string]$Wert) {
    $zeilen = New-Object System.Collections.Generic.List[string]
    if (Test-Path -LiteralPath $EnvDatei) {
        foreach ($z in [IO.File]::ReadAllLines($EnvDatei, $Utf8)) { $zeilen.Add($z) }
    }
    $name = [regex]::Escape($Name)
    $stelle = -1
    for ($i = 0; $i -lt $zeilen.Count; $i++) { if ($zeilen[$i] -match ('^\s*' + $name + '\s*=')) { $stelle = $i; break } }
    if ($stelle -lt 0) {
        for ($i = 0; $i -lt $zeilen.Count; $i++) { if ($zeilen[$i] -match ('^\s*#\s*' + $name + '\s*=')) { $stelle = $i; break } }
    }
    if ($stelle -ge 0) { $zeilen[$stelle] = "$Name=$Wert" } else { $zeilen.Add("$Name=$Wert") }
    # Eine vorhandene Datei behält beim Überschreiben ihre Zugriffsrechte (siehe Schuetze-EnvDatei).
    [IO.File]::WriteAllText($EnvDatei, (($zeilen -join "`n") + "`n"), $Utf8)
}

function Schuetze-EnvDatei {
    # .env enthält den geheimen Schlüssel und den Einrichtungscode: lesen und schreiben darf sie nur dein Konto.
    # (Wie chmod 600 unter macOS und Linux. Auf Laufwerken ohne NTFS geht das nicht; dann bleibt es beim Hinweis.)
    if (-not (Test-Path -LiteralPath $EnvDatei)) { return }
    $ok = $false
    try {
        $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $icacls = Join-Path $env:SystemRoot 'System32\icacls.exe'
        $r = Invoke-Nativ $icacls @($EnvDatei, '/inheritance:r', '/grant:r', ('*' + $sid + ':(F)')) -Sekunden 30
        $ok = ($r.Code -eq 0)
    } catch { $ok = $false }
    if (-not $ok) { Schreib 'Hinweis: Die Rechte der Datei .env ließen sich nicht auf dein Konto beschränken.' Yellow }
}

function Zufallsbytes([int]$Anzahl) {
    $bytes = New-Object byte[] $Anzahl
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    return , $bytes
}

function Neuer-Schluessel {
    return [Convert]::ToBase64String((Zufallsbytes 48)).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Neuer-Code {
    # 8 Zeichen ohne Verwechsler (kein 0/O, 1/I). 256 ist durch 32 teilbar, also gleich verteilt.
    $abc = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    $code = ''
    foreach ($b in (Zufallsbytes 8)) { $code += $abc[$b % 32] }
    return $code
}

function Code-Anzeige([string]$Code) {
    $c = ($Code -replace '[^A-Za-z0-9]', '').ToUpperInvariant()
    if ($c.Length -eq 8) { return $c.Substring(0, 4) + '-' + $c.Substring(4) }
    return $c
}

function Akte-Daten-Da {
    # Gibt es das Daten-Volume schon? Dann lief diese Akte schon einmal und hat vielleicht schon Konten.
    $r = Invoke-Nativ $script:Docker @('volume', 'inspect', '--format', '{{.Name}}', $DatenVolume) -Sekunden 40
    return ($r.Code -eq 0)
}

function Sichere-EnvDatei {
    if (-not (Test-Path -LiteralPath $EnvDatei)) {
        $vorlage = Join-Path $Wurzel '.env.example'
        $inhalt = ''
        if (Test-Path -LiteralPath $vorlage) { $inhalt = [IO.File]::ReadAllText($vorlage, $Utf8).Replace("`r`n", "`n") }
        [IO.File]::WriteAllText($EnvDatei, $inhalt, $Utf8)
        Schreib '.env angelegt (Einstellungen dieser Akte).'
    }
    if (-not (Env-Wert 'DJANGO_SECRET_KEY')) {
        Setze-EnvWert 'DJANGO_SECRET_KEY' (Neuer-Schluessel)
        Schreib 'Neuer geheimer Schlüssel für diese Akte in .env gespeichert.'
    }
    # Einen Einrichtungscode bekommt nur eine Akte, die noch nie lief. Eine Akte mit Daten (neue Version, zweiter
    # Start nach der Einrichtung) bekommt keinen neuen: Dort gibt es schon ein Konto oder den Notweg im Terminal.
    if (-not (Env-Wert 'AKTE_EINRICHTUNGSCODE') -and -not (Akte-Daten-Da)) {
        Setze-EnvWert 'AKTE_EINRICHTUNGSCODE' (Neuer-Code)
    }
    Schuetze-EnvDatei
}

function Lies-Port {
    $p = $env:AKTE_PORT
    if (-not $p) { $p = Env-Wert 'AKTE_PORT' }
    if ($p -match '^\d{2,5}$') { return [int]$p }
    return 8080
}

# ─── Docker ──────────────────────────────────────────────────────────────────────────────────────────────────
function Finde-Docker {
    if ($env:AKTE_DOCKER) {
        if (Test-Path -LiteralPath $env:AKTE_DOCKER) { return $env:AKTE_DOCKER }
        return $null
    }
    $treffer = Finde-Programm 'docker'
    if ($treffer) { return $treffer }
    # Ein Terminal, das vor der Docker-Installation offen war, kennt den Pfad noch nicht.
    foreach ($basis in @($env:ProgramFiles, $env:ProgramW6432)) {
        if (-not $basis) { continue }
        $kandidat = Join-Path $basis 'Docker\Docker\resources\bin\docker.exe'
        if (Test-Path -LiteralPath $kandidat) {
            # Auch für docker-credential-desktop, das Docker beim Laden von Bausteinen sucht.
            $env:Path = (Split-Path -Parent $kandidat) + ';' + $env:Path
            return $kandidat
        }
    }
    return $null
}

function Docker-Zustand {
    if (-not $script:Docker) { return 'fehlt' }
    # „docker version“ fragt den Docker-Dienst wie „docker info“, braucht aber Bruchteile der Zeit.
    $r = Invoke-Nativ $script:Docker @('version', '--format', '{{.Server.Version}}') -Sekunden 40
    if ($r.Code -eq 0 -and ([string]$r.Aus).Trim()) { return 'laeuft' }
    return 'aus'
}

function Akte-Container {
    $liste = @()
    if (-not $script:Docker) { return $liste }
    $r = Invoke-Nativ $script:Docker @('ps', '--filter', 'label=com.docker.compose.project=die-akte', '--filter', 'status=running', '--format', '{{.Names}}') -Sekunden 40
    if ($r.Code -ne 0) { return $liste }
    foreach ($z in ([string]$r.Aus -split "`r?`n")) {
        if ($z.Trim() -match '^die-akte-(api|web|proxy)-\d+$') { $liste += $Matches[1] }
    }
    return $liste
}

function Akte-Laeuft {
    $c = @(Akte-Container)
    return (($c -contains 'api') -and ($c -contains 'web') -and ($c -contains 'proxy'))
}

function Meldung-DockerFehlt {
    Schreib ''
    Schreib 'Docker Desktop fehlt. Die Akte läuft in Docker, deshalb brauchst du es einmal.' Yellow
    Schreib 'Installieren (PowerShell, eine Zeile):'
    Schreib '  winget install -e --id Docker.DockerDesktop'
    Schreib 'Dabei wichtig:'
    Schreib '  - Fragt der Installer „Per-user“ oder „All-users“: „All-users installation“ wählen.'
    Schreib '    Die empfohlene „Per-user“-Installation scheitert auf frischem Windows.'
    Schreib '  - Die Frage von Windows („Möchten Sie zulassen …“) mit „Ja“ beantworten.'
    Schreib '  - Danach den PC neu starten.'
    Schreib '  - Nach dem Neustart: Will ein schwarzes Fenster eine Taste (WSL-Aktualisierung), eine Taste drücken.'
    Schreib '    Im Docker-Fenster den Vertrag mit „Accept“ annehmen. Anmelden bei Docker ist nicht nötig.'
    Schreib '  - Dann die Akte noch einmal starten.'
    Schreib 'Ohne winget: https://www.docker.com/products/docker-desktop/ → „Download for Windows – AMD64“.'
    Schreib 'Docker Desktop ist für Privatleute, Bildung und kleine Firmen kostenlos.'
}

function Warte-AufDocker {
    if ((Docker-Zustand) -eq 'laeuft') { return }
    $grenze = 180
    if ($env:AKTE_DOCKER_WARTEN -match '^\d+$') { $grenze = [int]$env:AKTE_DOCKER_WARTEN }
    $desktop = $null
    if (-not $env:AKTE_DOCKER) {
        foreach ($basis in @($env:ProgramFiles, $env:ProgramW6432)) {
            if (-not $basis) { continue }
            $kandidat = Join-Path $basis 'Docker\Docker\Docker Desktop.exe'
            if (Test-Path -LiteralPath $kandidat) { $desktop = $kandidat; break }
        }
    }
    if ($desktop) {
        Schreib 'Docker Desktop läuft noch nicht. Ich starte es.'
        try { Start-Process -FilePath $desktop | Out-Null } catch { Schreib 'Docker Desktop ließ sich nicht starten. Öffne es bitte selbst (Startmenü: „Docker Desktop“).' Yellow }
    } else {
        Schreib 'Docker antwortet noch nicht.'
    }
    Schreib 'Fragt ein Docker-Fenster nach dem Vertrag: „Accept“ klicken. Will ein schwarzes Fenster eine Taste: eine Taste drücken.'
    if ($grenze -ge 60) { Schreib "Ich warte bis zu $([int][math]::Ceiling($grenze / 60)) Minuten auf Docker …" }
    else { Schreib "Ich warte bis zu $grenze Sekunden auf Docker …" }
    $beginn = Get-Date
    $letzte = 0
    while (((Get-Date) - $beginn).TotalSeconds -lt $grenze) {
        Start-Sleep -Seconds 3
        if ((Docker-Zustand) -eq 'laeuft') { Schreib 'Docker läuft.' Green; return }
        $sek = [int]((Get-Date) - $beginn).TotalSeconds
        if ($sek - $letzte -ge 15) { Schreib "  … Docker startet noch ($sek Sekunden)"; $letzte = $sek }
    }
    Schreib ''
    Schreib 'Docker startet nicht.' Red
    $r = Invoke-Nativ $script:Docker @('version') -Sekunden 40
    $letzteZeile = @(([string]$r.Fehler) -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
    if ($letzteZeile) { Schreib "Docker meldet: $letzteZeile" }
    Schreib 'Was hilft:'
    Schreib '  - Docker Desktop öffnen und nachsehen, ob es etwas fragt (Vertrag „Accept“, WSL-Fenster: Taste drücken).'
    Schreib '  - Meldet Docker „WSL not installed“ direkt nach der Installation: Docker Desktop schließen (Quit),'
    Schreib '    eine Minute warten, Docker Desktop wieder öffnen. Hilft das nicht: PC neu starten.'
    Schreib '  - Dann die Akte noch einmal starten.'
    Ende 4
}

function Pruefe-Platz {
    try {
        $laufwerk = $env:SystemDrive.TrimEnd(':')
        $frei = (Get-PSDrive -Name $laufwerk -ErrorAction Stop).Free
        if ($frei -and $frei -lt 10GB) {
            Schreib ('Achtung: Auf {0}: sind nur noch {1:N1} GB frei. Docker und die Akte brauchen beim ersten Start einige GB.' -f $laufwerk, ($frei / 1GB)) Yellow
        }
    } catch { }
}

function Port-Frei([int]$Port) {
    $lauscher = $null
    try {
        $lauscher = New-Object System.Net.Sockets.TcpListener -ArgumentList ([System.Net.IPAddress]::Loopback), $Port
        $lauscher.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($lauscher) { try { $lauscher.Stop() } catch { } }
    }
}

function Sichere-Port {
    $port = Lies-Port
    if (Port-Frei $port) { return $port }
    $c = @(Akte-Container)
    if ($c -contains 'proxy') { return $port }   # Das ist die Akte selbst.
    Schreib "Port $port ist belegt: Ein anderes Programm benutzt diese Adresse schon." Yellow
    if ($env:AKTE_PORT) {
        Schreib "Die Umgebungsvariable AKTE_PORT=$($env:AKTE_PORT) legt den Port fest. Setz sie auf einen freien Port (z. B. 8081) oder entferne sie."
        Ende 5
    }
    for ($p = $port + 1; $p -le $port + 20; $p++) {
        if (Port-Frei $p) {
            Setze-EnvWert 'AKTE_PORT' "$p"
            Schreib "Die Akte nimmt stattdessen Port $p (gespeichert in .env als AKTE_PORT=$p)."
            Schreib 'War Claude schon mit der Akte verbunden: start\AGENT-VERBINDEN.cmd noch einmal ausführen.'
            return $p
        }
    }
    Schreib "Zwischen $($port + 1) und $($port + 20) ist kein Port frei. Trag in .env bei AKTE_PORT einen freien Port ein (z. B. AKTE_PORT=9090)."
    Ende 5
}

function Pruefe-Entpackt {
    $ausZip = ($PSScriptRoot -match '\.zip(\\|$)')
    if ($ausZip -or -not (Test-Path -LiteralPath (Join-Path $Wurzel 'compose.yaml'))) {
        Schreib ''
        Schreib 'Bitte zuerst entpacken: Rechtsklick auf die ZIP-Datei → „Alle extrahieren“.' Yellow
        Schreib 'Danach im entpackten Ordner „start“ öffnen und START-AKTE doppelklicken.'
        # Achtung: „ und “ beenden in PowerShell einen "…"-Text. Deutsche Anführungszeichen nur in '…'.
        if (-not $ausZip) { Schreib ('(Neben dem Ordner „start“ fehlt die Datei compose.yaml: ' + $Wurzel + ')') }
        Ende 2
    }
}

function Pruefe-AkteLaeuft {
    $script:Docker = Finde-Docker
    if (-not $script:Docker) { Meldung-DockerFehlt; Ende 3 }
    if ((Docker-Zustand) -ne 'laeuft') {
        Schreib 'Docker läuft nicht, also auch die Akte nicht. Starte zuerst die Akte:' Yellow
        Schreib '  Doppelklick auf start\START-AKTE.cmd'
        Schreib "  (Agent: $AgentAufruf start -Still)"
        Ende 4
    }
    if (-not (Akte-Laeuft)) {
        Schreib 'Die Akte läuft nicht. Starte sie zuerst:' Yellow
        Schreib '  Doppelklick auf start\START-AKTE.cmd'
        Schreib "  (Agent: $AgentAufruf start -Still)"
        Ende 10
    }
}

# ─── Einrichtung (erstes Konto) ──────────────────────────────────────────────────────────────────────────────
function Einrichtung-Stand([int]$Port) {
    # Fragt die Akte: GET /api/v1/auth/einrichtung/ → {"offen": bool, "grund": "offen" | "kein_code" | "eingerichtet"}
    $r = Http-Hole "http://127.0.0.1:$Port/api/v1/auth/einrichtung/"
    $erreichbar = [bool]($r -and $r.Code -lt 500)
    if (-not $r -or $r.Code -ne 200) { return [pscustomobject]@{ Erreichbar = $erreichbar; Offen = $false; Grund = $null } }
    $offen = [bool]($r.Text -match '"offen"\s*:\s*true')
    $grund = $null
    if ($r.Text -match '"grund"\s*:\s*"(offen|kein_code|eingerichtet)"') { $grund = $Matches[1] }
    if (-not $grund) {
        # Eine Akte ohne „grund“ in der Antwort: aus den übrigen Angaben ableiten.
        if ($offen) { $grund = 'offen' }
        elseif (Env-Wert 'AKTE_EINRICHTUNGSCODE') { $grund = 'eingerichtet' }
        else { $grund = 'kein_code' }
    }
    return [pscustomobject]@{ Erreichbar = $true; Offen = $offen; Grund = $grund }
}

function Entferne-VerbrauchtenCode {
    # Das erste Konto steht: Der Code wird nie wieder gebraucht. Ohne Code in .env öffnet auch ein später
    # deaktiviertes Konto die Einrichtung nicht wieder (wirkt beim nächsten Start der Akte).
    if (-not (Env-Wert 'AKTE_EINRICHTUNGSCODE')) { return }
    Setze-EnvWert 'AKTE_EINRICHTUNGSCODE' ''
    Schreib 'Das erste Konto steht. Den Einrichtungscode habe ich aus .env gelöscht; er wird nicht mehr gebraucht.'
}

function Meldung-Notweg {
    # Der Weg ohne Browser und ohne Code: akte_einrichten fragt Benutzername und Passwort im Terminal.
    Schreib 'Das erste Konto legt ein Mensch dann im Terminal an. Er braucht dafür keinen Code; das Passwort bleibt beim'
    Schreib 'Tippen unsichtbar (PowerShell öffnen, diese Zeile eingeben):'
    Schreib "  cd `"$Wurzel`"; docker compose exec api python manage.py akte_einrichten"
}

function Meldung-KeinCode {
    Schreib 'Es gibt noch kein Konto und keinen Einrichtungscode: Diese Akte hat Daten aus einem früheren Start.' Yellow
    Meldung-Notweg
}

function Oeffne-Browser([string]$Url) {
    # $true, wenn ein Browser gestartet wurde. Schreibt die Adresse nie aus: Sie kann den Einrichtungscode tragen.
    # AKTE_BROWSER (ein Programm statt des Standard-Browsers) gilt nur für die Prüfskripte (AKTE_STARTER_TEST=1).
    if ($OhneBrowser -or $env:AKTE_OHNE_BROWSER -eq '1') { return $false }
    try {
        if ($env:AKTE_BROWSER -and $env:AKTE_STARTER_TEST -eq '1') {
            Start-Process -FilePath $env:AKTE_BROWSER -ArgumentList @(ConvertTo-Argument $Url) | Out-Null
        } else {
            Start-Process -FilePath $Url | Out-Null
        }
        return $true
    } catch {
        return $false
    }
}

function Zeige-Einrichtung([string]$Basis) {
    # Der Code geht nur an den Browser (Fragment der Adresse), nie in eine Konsole, auch nicht nach einem Doppelklick.
    $seite = "$Basis/akte/einrichten"
    $code = Code-Anzeige (Env-Wert 'AKTE_EINRICHTUNGSCODE')
    Schreib 'Die Akte läuft. Jetzt fehlt nur noch dein erstes Konto.' Green
    $ziel = $seite
    if ($code) { $ziel = $seite + '#code=' + $code }
    $imBrowser = Oeffne-Browser $ziel
    if ($imBrowser) {
        Schreib 'Der Browser ist offen: wähl dort Name und Passwort.'
        Schreib "Seite: $seite"
        if ($code) { Schreib 'Der Einrichtungscode ist dort schon eingetragen. Seite geschlossen? START-AKTE noch einmal starten.' }
    } else {
        Schreib "Kein Browser ist aufgegangen. Seite: $seite" Yellow
    }
    if (-not $code) {
        # Die laufende Akte kennt noch einen alten Code, .env nicht mehr (selten, z. B. nach Handarbeit an .env).
        Schreib 'In .env steht kein Einrichtungscode mehr.' Yellow
    }
    if (-not $code -or -not $imBrowser) { Meldung-Notweg }
    Schreib 'Passwort: mindestens 10 Zeichen. Das Passwort tippst nur du, nie ein Agent.'
}

# ─── Status ──────────────────────────────────────────────────────────────────────────────────────────────────
function Agent-Verbunden([int]$Port) {
    # Liest die Benutzer-Einstellungen von Claude Code (.claude.json, Abschnitt mcpServers.akte).
    $ordner = $env:USERPROFILE
    if ($env:CLAUDE_CONFIG_DIR) { $ordner = $env:CLAUDE_CONFIG_DIR }
    $datei = Join-Path $ordner '.claude.json'
    if (-not (Test-Path -LiteralPath $datei)) { return $false }
    $text = ''
    try { $text = [IO.File]::ReadAllText($datei, $Utf8) } catch { return $false }
    try {
        Add-Type -AssemblyName System.Web.Extensions
        $leser = New-Object System.Web.Script.Serialization.JavaScriptSerializer
        $leser.MaxJsonLength = [int]::MaxValue
        $daten = $leser.DeserializeObject($text)
        if (-not ($daten -is [System.Collections.IDictionary]) -or -not $daten.ContainsKey('mcpServers')) { return $false }
        $server = $daten['mcpServers']
        if (-not ($server -is [System.Collections.IDictionary]) -or -not $server.ContainsKey('akte')) { return $false }
        $eintrag = $server['akte']
        $basis = ''
        if ($eintrag -is [System.Collections.IDictionary] -and $eintrag.ContainsKey('env')) {
            $umgebung = $eintrag['env']
            if ($umgebung -is [System.Collections.IDictionary] -and $umgebung.ContainsKey('AKTE_BASIS')) { $basis = [string]$umgebung['AKTE_BASIS'] }
        }
        if ($basis -match ':(\d+)/?$') { return ([int]$Matches[1] -eq $Port) }
        return $true
    } catch {
        return [bool]($text -match '"akte"\s*:\s*\{[^{}]*"akte-mcp"')
    }
}

function Hole-Status {
    # Für Agenten: Der Einrichtungscode gehört nicht hierher (siehe Kopf der Datei).
    $port = Lies-Port
    $script:Docker = Finde-Docker
    $docker = Docker-Zustand
    $laeuft = $false
    if ($docker -eq 'laeuft') { $laeuft = Akte-Laeuft }
    $offen = $false
    $grund = $null
    if ($laeuft) {
        $stand = Einrichtung-Stand $port
        $offen = [bool]$stand.Offen
        $grund = $stand.Grund
    }
    $url = "http://localhost:$port/akte"
    if ($offen) { $url = "http://localhost:$port/akte/einrichten" }
    $akte = 'aus'
    if ($laeuft) { $akte = 'laeuft' }
    return [ordered]@{
        docker            = $docker
        akte              = $akte
        url               = $url
        einrichtung_offen = $offen
        einrichtung_grund = $grund
        agent_verbunden   = [bool](Agent-Verbunden $port)
    }
}

# ─── Befehle ─────────────────────────────────────────────────────────────────────────────────────────────────
function Befehl-Start {
    Pruefe-Entpackt
    Schreib 'Die Akte startet.' Cyan
    Pruefe-Platz
    $script:Docker = Finde-Docker
    if (-not $script:Docker) { Meldung-DockerFehlt; Ende 3 }
    Warte-AufDocker
    Sichere-EnvDatei
    $port = Sichere-Port

    Schreib 'Die Akte wird gebaut und gestartet. Beim ersten Mal dauert das 3 bis 10 Minuten.'
    $argumente = @('compose', 'up', '-d', '--build', '--wait')
    $code = 0
    if ($Still) {
        $protokoll = Join-Path ([IO.Path]::GetTempPath()) 'die-akte-start.log'
        $r = Invoke-Nativ $script:Docker $argumente -Sekunden 1800 -Ordner $Wurzel -Fortschritt {
            param($s) if ($s % 30 -eq 0) { Schreib "  … baut und startet noch ($s Sekunden)" }
        }
        try { [IO.File]::WriteAllText($protokoll, ([string]$r.Aus + "`n" + [string]$r.Fehler), $Utf8) } catch { }
        $code = $r.Code
        if ($code -ne 0) {
            Schreib 'Letzte Zeilen von Docker:'
            Schreib-Schluss $r 25
            Schreib "Ganzes Protokoll: $protokoll"
        }
    } else {
        Push-Location -LiteralPath $Wurzel
        $vorher = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $script:Docker @argumente
            $code = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $vorher
            Pop-Location
        }
    }
    if ($code -ne 0) {
        Schreib ''
        Schreib 'Start fehlgeschlagen.' Red
        Schreib 'Häufige Gründe:'
        Schreib '  - Kein Internet beim ersten Start (Docker lädt Bausteine nach).'
        Schreib '  - Zu wenig Speicherplatz (10 GB frei einplanen).'
        Schreib '  - Docker Desktop hängt: Docker Desktop beenden (Wal-Symbol unten rechts → Quit), neu öffnen, noch einmal starten.'
        Schreib '  - Genaueres im Akte-Ordner: docker compose logs api'
        Ende 6
    }

    $stand = $null
    for ($i = 0; $i -lt 15; $i++) {
        $stand = Einrichtung-Stand $port
        if ($stand.Erreichbar) { break }
        Start-Sleep -Seconds 2
    }
    $basis = "http://localhost:$port"
    Schreib ''
    if ($stand.Offen) {
        Zeige-Einrichtung $basis
    } else {
        $url = "$basis/akte"
        Schreib "Die Akte läuft: $url" Green
        if (-not $stand.Erreichbar) { Schreib 'Die Seite antwortet noch nicht. Warte eine Minute und lade sie dann neu.' Yellow }
        if ($stand.Grund -eq 'eingerichtet') { Entferne-VerbrauchtenCode }
        elseif ($stand.Grund -eq 'kein_code') { Meldung-KeinCode }
        if (Oeffne-Browser $url) { Schreib "Browser geöffnet: $url" }
    }
    Schreib 'Sie läuft im Hintergrund weiter, auch nach einem PC-Neustart, sobald Docker Desktop läuft.'
    Schreib 'Stoppen: start\STOP-AKTE.cmd'
    if (-not (Agent-Verbunden $port)) { Schreib 'Claude Code verbinden: start\AGENT-VERBINDEN.cmd' }
    Ende 0
}

function Befehl-Stop {
    Pruefe-Entpackt
    $script:Docker = Finde-Docker
    if (-not $script:Docker -or (Docker-Zustand) -ne 'laeuft') {
        Schreib 'Docker läuft nicht, die Akte ist also schon aus.'
        Ende 0
    }
    if (Test-Path -LiteralPath $EnvDatei) {
        $r = Invoke-Nativ $script:Docker @('compose', 'stop') -Ordner $Wurzel -Sekunden 180
    } else {
        # Ohne .env lädt docker compose das Projekt nicht; dann über die Projekt-Kennung anhalten.
        $r = Invoke-Nativ $script:Docker @('ps', '-q', '--filter', 'label=com.docker.compose.project=die-akte') -Sekunden 40
        $kennungen = @(([string]$r.Aus) -split "`r?`n" | Where-Object { $_.Trim() })
        if ($kennungen.Count -gt 0) { $r = Invoke-Nativ $script:Docker (@('stop') + $kennungen) -Sekunden 180 }
    }
    if ($r.Code -eq 0) {
        Schreib 'Die Akte ist angehalten. Deine Daten bleiben erhalten.' Green
        Schreib 'Wieder starten: start\START-AKTE.cmd'
        Ende 0
    }
    Schreib 'Anhalten hat nicht geklappt:' Red
    Schreib-Schluss $r
    Ende 6
}

function Befehl-Status {
    $status = Hole-Status
    if ($Json) {
        SchreibRoh ($status | ConvertTo-Json -Compress)
        Ende 0
    }
    $dockerText = @{ fehlt = 'fehlt'; aus = 'aus (oder startet noch)'; laeuft = 'läuft' }[$status.docker]
    Schreib "Docker:            $dockerText"
    if ($status.akte -eq 'laeuft') { Schreib "Akte:              läuft – $($status.url)" } else { Schreib 'Akte:              aus' }
    if ($status.einrichtung_offen) {
        Schreib "Erstes Konto:      fehlt noch → $($status.url)"
    } elseif ($status.einrichtung_grund -eq 'kein_code') {
        Schreib 'Erstes Konto:      fehlt; ohne Einrichtungscode geht es nur im Terminal (akte_einrichten)'
    } elseif ($status.akte -eq 'laeuft') {
        Schreib 'Erstes Konto:      angelegt'
    }
    $agentText = 'nein'
    if ($status.agent_verbunden) { $agentText = 'ja' }
    Schreib "Claude verbunden:  $agentText"
    Ende 0
}

function Befehl-Demo {
    Pruefe-Entpackt
    Pruefe-AkteLaeuft
    Schreib 'Ich lade die erfundene Demo-Akte „Freie Stadt Musterhafen“ (bis zu einer Minute) …'
    $r = Invoke-Nativ $script:Docker @('compose', 'exec', '-T', 'api', 'python', 'manage.py', 'akte_demo') -Ordner $Wurzel -Sekunden 600
    $port = Lies-Port
    $url = "http://localhost:$port/akte/demo-musterhafen"
    if ($r.Code -eq 0) {
        Schreib "Demo geladen: $url" Green
    } elseif (([string]$r.Aus + [string]$r.Fehler) -match 'gibt es schon') {
        Schreib "Die Demo ist schon da: $url" Green
    } else {
        Schreib 'Die Demo ließ sich nicht laden:' Red
        Schreib-Schluss $r
        Ende 6
    }
    Schreib 'Zum Ansehen meldest du dich im Browser mit deinem Konto an.'
    if (Oeffne-Browser $url) { Schreib "Browser geöffnet: $url" }
    Ende 0
}

function Sichere-LokalBin {
    # Claude Code und uv liegen in %USERPROFILE%\.local\bin. Der Ordner muss in den Pfad: für diese Sitzung und
    # dauerhaft für neue Fenster (der Claude-Installer vergisst das auf frischem Windows).
    $lokal = Join-Path $env:USERPROFILE '.local\bin'
    $inSitzung = $false
    foreach ($teil in ($env:Path -split ';')) {
        if ($teil -and [Environment]::ExpandEnvironmentVariables($teil).TrimEnd('\') -ieq $lokal) { $inSitzung = $true }
    }
    if (-not $inSitzung) { $env:Path = $env:Path.TrimEnd(';') + ';' + $lokal }
    if ($env:AKTE_PFAD_NICHT_AENDERN -eq '1') { return $false }
    $schluessel = $null
    try {
        $schluessel = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
        $alt = [string]$schluessel.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        foreach ($teil in ($alt -split ';')) {
            if ($teil -and [Environment]::ExpandEnvironmentVariables($teil).TrimEnd('\') -ieq $lokal) { return $false }
        }
        $neu = '%USERPROFILE%\.local\bin'
        if ($alt.Trim()) { $neu = $alt.TrimEnd(';') + ';' + $neu }
        $schluessel.SetValue('Path', $neu, [Microsoft.Win32.RegistryValueKind]::ExpandString)
        # Windows Bescheid geben, damit neue Fenster den Pfad kennen.
        [Environment]::SetEnvironmentVariable('AKTE_PFAD_SIGNAL', '1', 'User')
        [Environment]::SetEnvironmentVariable('AKTE_PFAD_SIGNAL', $null, 'User')
        Schreib "Den Ordner $lokal habe ich dauerhaft in deinen Benutzer-Pfad eingetragen."
        return $true
    } catch {
        Schreib "Den Benutzer-Pfad konnte ich nicht ändern: $($_.Exception.Message)" Yellow
        return $false
    } finally {
        if ($schluessel) { $schluessel.Close() }
    }
}

function Finde-Konto([string]$Grund) {
    if ($Konto) { return $Konto }
    # Wer an der Akte arbeiten darf: aktive Konten der Redaktion oder Superuser, dieselbe Auswahl wie bei der
    # Einrichtung. akte_konten gibt je Konto eine Zeile KONTO:name aus.
    $r = Invoke-Nativ $script:Docker @('compose', 'exec', '-T', 'api', 'python', 'manage.py', 'akte_konten') -Ordner $Wurzel -Sekunden 120
    $konten = @()
    foreach ($z in ([string]$r.Aus -split "`r?`n")) { if ($z -match '^KONTO:(.+)$') { $konten += $Matches[1].Trim() } }
    if ($konten.Count -eq 1) { return $konten[0] }
    if ($konten.Count -eq 0) {
        Schreib 'Ich finde kein Konto für die Redaktion.' Yellow
        if ($r.Code -ne 0) { Schreib-Schluss $r 5 }
        if ($Grund -eq 'kein_code') { Meldung-KeinCode }
        else { Schreib 'Leg zuerst im Browser dein erstes Konto an und starte das hier dann noch einmal.' }
        Ende 9
    }
    Schreib ('Es gibt mehrere Konten: ' + ($konten -join ', ') + '. Sag mir, welches Claude benutzen soll:') Yellow
    Schreib "  $AgentAufruf agent -Konto NAME"
    Ende 9
}

function Installiere-Uv {
    # Gibt '' zurück, wenn der Installer gelaufen ist, sonst den Grund.
    $datei = Join-Path ([IO.Path]::GetTempPath()) ('uv-installer-' + $UvVersion + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8) + '.ps1')
    try {
        try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
        try { Invoke-WebRequest -UseBasicParsing -Uri $UvInstallerUrl -OutFile $datei }
        catch { return "Laden von $UvInstallerUrl fehlgeschlagen: $($_.Exception.Message)" }
        $ist = (Get-FileHash -Algorithm SHA256 -LiteralPath $datei).Hash.ToLowerInvariant()
        if ($ist -ne $UvInstallerSha256) {
            return "Der geladene Installer hat nicht die erwartete Prüfsumme (erwartet $UvInstallerSha256, bekommen $ist). Ich führe ihn nicht aus."
        }
        $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        # Ohne Variablen, mit denen der Aufrufer den Installer auf eine andere Download-Quelle oder einen anderen Ordner
        # umlenken könnte: Er soll genau die geprüfte Version an den üblichen Ort legen.
        $umlenker = @('UV_DOWNLOAD_URL', 'INSTALLER_DOWNLOAD_URL', 'UV_INSTALLER_GITHUB_BASE_URL', 'UV_INSTALLER_GHE_BASE_URL',
            'UV_INSTALL_DIR', 'CARGO_DIST_FORCE_INSTALL_DIR', 'UV_UNMANAGED_INSTALL', 'UV_GITHUB_TOKEN')
        $r = Invoke-Nativ $ps @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $datei) -Sekunden 600 -OhneVariablen $umlenker
        if ($r.Code -ne 0) {
            $letzte = @(([string]$r.Aus + "`n" + [string]$r.Fehler) -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 5)
            return ('Der Installer meldet: ' + ($letzte -join ' / '))
        }
        return ''
    } finally {
        Remove-Item -LiteralPath $datei -Force -ErrorAction SilentlyContinue
    }
}

function Befehl-Agent {
    Pruefe-Entpackt
    Schreib 'Ich verbinde Claude Code mit deiner Akte.' Cyan
    $pfadNeu = Sichere-LokalBin

    $claude = Finde-Programm 'claude' @((Join-Path $env:USERPROFILE '.local\bin\claude.exe'), (Join-Path ([string]$env:APPDATA) 'npm\claude.cmd'))
    if (-not $claude) {
        Schreib ''
        Schreib 'Claude Code fehlt.' Yellow
        Schreib 'Installieren wie im README beschrieben (Schnellstart, Schritt 1; offizieller Installer von claude.ai).'
        Schreib 'Danach ein neues Terminal-Fenster öffnen, claude starten und anmelden (Claude-Abo Pro oder Max).'
        Schreib 'Dann AGENT-VERBINDEN noch einmal starten.'
        Ende 7
    }

    Pruefe-AkteLaeuft
    $port = Lies-Port
    $stand = Einrichtung-Stand $port
    if ($stand.Offen) {
        Schreib 'Es gibt noch kein Konto. Leg zuerst im Browser dein erstes Konto an:' Yellow
        Schreib "  http://localhost:$port/akte/einrichten"
        Schreib 'Ist die Seite zu oder das Feld für den Einrichtungscode leer: START-AKTE noch einmal starten'
        Schreib "  (Doppelklick, oder als Agent: $AgentAufruf start -Still). Er öffnet die Seite mit dem Code."
        Schreib 'Geht kein Browser auf: Notweg im Terminal, ohne Code (fragt Benutzername und Passwort):'
        Schreib "  cd `"$Wurzel`"; docker compose exec api python manage.py akte_einrichten"
        Schreib 'Danach AGENT-VERBINDEN noch einmal starten.'
        Ende 9
    }
    if ($stand.Grund -eq 'eingerichtet') { Entferne-VerbrauchtenCode }
    $kontoName = Finde-Konto $stand.Grund
    Schreib "Konto für Claude: $kontoName"

    $uvKandidaten = @((Join-Path $env:USERPROFILE '.local\bin\uvx.exe'))
    if ($env:XDG_BIN_HOME) { $uvKandidaten += (Join-Path $env:XDG_BIN_HOME 'uvx.exe') }
    $uvx = Finde-Programm 'uvx' $uvKandidaten
    if (-not $uvx) {
        Schreib "uv fehlt (damit startet Claude den Akte-Baustein). Ich installiere uv $UvVersion mit dem offiziellen Installer von astral.sh …"
        $grund = Installiere-Uv
        $uvx = Finde-Programm 'uvx' $uvKandidaten
        if (-not $uvx) {
            Schreib 'uv ließ sich nicht installieren.' Red
            if ($grund) { Schreib "  $grund" }
            Schreib 'Von Hand (PowerShell, drei Zeilen: laden, Prüfsumme vergleichen, erst dann ausführen):'
            Schreib ('  Invoke-WebRequest -UseBasicParsing "' + $UvInstallerUrl + '" -OutFile "$env:TEMP\uv-install.ps1"')
            Schreib ('  (Get-FileHash "$env:TEMP\uv-install.ps1").Hash   muss lauten: ' + $UvInstallerSha256.ToUpperInvariant())
            Schreib '  powershell -NoProfile -ExecutionPolicy Bypass -File "$env:TEMP\uv-install.ps1"'
            Ende 8
        }
        Schreib 'uv ist installiert.' Green
    }

    # Vorwärmen: Python 3.12 und Pakete einmal laden, damit Claude beim ersten Start nicht in die Zeitgrenze läuft.
    Schreib 'Ich lade den Akte-Baustein für Claude (einmalig, bis zu 2 Minuten) …'
    $r = Invoke-Nativ $uvx @('--python', '3.12', '--from', $McpQuelle, 'akte', '--help') -Ordner $StartOrdner -Sekunden 900 -Fortschritt {
        param($s) if ($s % 30 -eq 0) { Schreib "  … lädt noch ($s Sekunden)" }
    }
    if ($r.Code -ne 0) {
        Schreib 'Der Akte-Baustein ließ sich nicht laden.' Red
        Schreib-Schluss $r 15
        Schreib "Quelle: $McpQuelle"
        Schreib 'Prüf die Internetverbindung und versuch es noch einmal.'
        Ende 11
    }

    $r = Invoke-Nativ $script:Docker @('compose', 'exec', '-T', 'api', 'python', 'manage.py', 'akte_token', $kontoName) -Ordner $Wurzel -Sekunden 120
    $token = ''
    foreach ($z in ([string]$r.Aus -split "`r?`n")) {
        $t = $z.Trim()
        if ($t -match '^[A-Za-z0-9_\-]{20,}$') { $token = $t }
    }
    if ($r.Code -ne 0 -or -not $token) {
        Schreib 'Den Schlüssel für Claude (Token) konnte ich nicht holen.' Red
        $fehler = @(([string]$r.Fehler) -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 3)
        foreach ($z in $fehler) { Schreib "  $z" }
        Ende 12
    }

    # Alten Eintrag ersetzen (auch einen ordnergebundenen aus älteren Anleitungen).
    foreach ($bereich in @('local', 'user')) {
        [void](Invoke-Nativ $claude @('mcp', 'remove', 'akte', '-s', $bereich) -Ordner $StartOrdner -Sekunden 60)
    }
    $basisAdresse = "http://127.0.0.1:$port"
    $r = Invoke-Nativ $claude @('mcp', 'add', '--scope', 'user', 'akte', '-e', "AKTE_BASIS=$basisAdresse", '-e', "AKTE_TOKEN=$token", '--', 'uvx', '--python', '3.12', '--from', $McpQuelle, 'akte-mcp') -Ordner $StartOrdner -Sekunden 120
    if ($r.Code -ne 0) {
        Schreib 'claude mcp add ist fehlgeschlagen:' Red
        Schreib-Schluss $r 10 $token
        Ende 13
    }

    Schreib ''
    Schreib 'Claude Code ist jetzt mit deiner Akte verbunden.' Green
    Schreib 'Fertig. Beende Claude (/exit) und starte es neu mit: claude --continue'
    if ($pfadNeu) {
        if ($Fenster) {
            Schreib 'Wichtig: Öffne dafür ein neues Terminal-Fenster (das alte kennt den neuen Pfad noch nicht).'
        } else {
            Schreib "Wichtig: Öffne dafür ein neues Terminal-Fenster und geh in denselben Ordner: cd `"$StartOrdner`""
        }
    }
    Schreib 'Danach zeigt /mcp den Eintrag „akte“ als verbunden.'
    Schreib 'Der Schlüssel für die Verbindung steht jetzt in deiner Claude-Einstellung (.claude.json). Gib diese Datei nicht weiter.'
    Ende 0
}

function Befehl-Hilfe {
    Schreib 'Die Akte – Starter für Windows'
    Schreib ''
    Schreib "  $AgentAufruf start      starten (Standard)"
    Schreib "  $AgentAufruf stop       anhalten"
    Schreib "  $AgentAufruf status     Zustand; mit -Json für Agenten"
    Schreib "  $AgentAufruf agent      Claude Code verbinden"
    Schreib "  $AgentAufruf demo       Demo-Akte laden"
    Schreib ''
    Schreib 'Schalter: -Still (keine Rückfragen), -Json (nur bei status), -Konto NAME, -OhneBrowser'
    Ende 0
}

# ─── Ablauf ──────────────────────────────────────────────────────────────────────────────────────────────────
try {
    $befehlKlein = $Befehl.ToLowerInvariant()
    if ($Json -and $befehlKlein -ne 'status') {
        # Bei allen anderen Befehlen bliebe die Ausgabe mit -Json sonst einfach leer.
        SchreibJsonFehler "-Json gibt es nur beim Befehl status (aufgerufen: $Befehl)."
        Ende 1
    }
    switch ($befehlKlein) {
        'start' { Befehl-Start }
        'stop' { Befehl-Stop }
        'status' { Befehl-Status }
        'agent' { Befehl-Agent }
        'demo' { Befehl-Demo }
        { $_ -in @('hilfe', 'help', '-h', '--help', '/?') } { Befehl-Hilfe }
        default {
            Schreib "Unbekannter Befehl: $Befehl" Yellow
            Befehl-Hilfe
        }
    }
} catch {
    if ($Json) {
        # Ein Agent liest bei -Json nur JSON: auch ein Fehler kommt als JSON.
        SchreibJsonFehler ('Unerwarteter Fehler: ' + $_.Exception.Message)
        Ende 1
    }
    Schreib ''
    Schreib "Unerwarteter Fehler: $($_.Exception.Message)" Red
    Schreib "Stelle: $($_.InvocationInfo.PositionMessage)"
    Schreib 'Bitte melde das mit dieser Ausgabe: https://github.com/ThePyth0nKid/die-akte/issues'
    Ende 1
}
