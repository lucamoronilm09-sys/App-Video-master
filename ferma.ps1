# Ferma AI Video Maker: uccide per command-line (robusto con npm/node figli).
# Match sul nome reale della cartella progetto: "App Video" (con spazio) non
# compare mai nei percorsi e faceva sì che questo script non uccidesse nulla
# (porte restavano occupate -> i nuovi avvii morivano all'istante).
#
# MAI uccidere la propria catena di lancio: quando si esegue .\ferma.bat,
# Windows crea `cmd.exe /c "...\ferma.bat"` la cui command-line contiene il
# progetto e matcherebbe il filtro cmd -> lo script uccideva il proprio
# lanciatore a ogni run (finto "(1 processi)" infinito + terminale inchiodato;
# stesso rischio per lo step di pulizia di avvia.bat). Per questo i PID
# propri/antenati e le cmdline ferma*/avvia* sono sempre esclusi.
$ErrorActionPreference = "SilentlyContinue"
$root = "App-Video-master"
$killed = @()

function Get-ProtectedPids {
    $protected = @{}
    $pid = $PID
    while ($pid -and $pid -gt 0) {
        if ($protected.ContainsKey($pid)) { break }
        $protected[$pid] = $true
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$pid"
        if (-not $proc) { break }
        $ppid = $proc.ParentProcessId
        if (-not $ppid -or $ppid -eq $pid) { break }
        $pid = $ppid
    }
    return $protected
}

function Test-SelfLauncher($cli) {
    return ($cli -like "*ferma.bat*" -or $cli -like "*ferma.ps1*" -or $cli -like "*avvia.bat*")
}

$protected = Get-ProtectedPids

function Get-Role($p) {
    $cli = $p.CommandLine
    if ($p.Name -eq "python.exe" -and $cli -like "*uvicorn*") { return "backend (uvicorn)" }
    if ($p.Name -eq "node.exe") { return "frontend (next/node)" }
    if ($p.Name -eq "cmd.exe") { return "wrapper terminale" }
    if ($p.Name -eq "ffmpeg.exe") { return "render ffmpeg orfano" }
    return $p.Name
}

function Stop-Matching($processes) {
    foreach ($p in $processes) {
        if ($protected.ContainsKey($p.ProcessId)) { continue }
        if (Test-SelfLauncher($p.CommandLine)) { continue }
        $desc = "$($p.Name) PID $($p.ProcessId) [$(Get-Role $p)]"
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        if ($?) { $script:killed += $desc }
    }
}

# Backend: uvicorn del progetto
Stop-Matching (Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*$root*" -and $_.CommandLine -like "*uvicorn*" })

# Frontend: next del progetto + wrapper cmd/npm solo se citano il progetto
# (il cmd wrapper esce da solo quando muore il suo node; node.exe matcha
# sempre perché esegue ...\frontend\node_modules\next\...)
Stop-Matching (Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
    Where-Object { $_.CommandLine -like "*$root*" })
Stop-Matching (Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" |
    Where-Object { $_.CommandLine -like "*$root*" })

# Render ffmpeg orfani del progetto (input/output in data\projects)
Stop-Matching (Get-CimInstance Win32_Process -Filter "Name='ffmpeg.exe'" |
    Where-Object { $_.CommandLine -like "*$root*" })

if ($killed.Count -gt 0) {
    Write-Output "AI Video Maker fermato ($($killed.Count) processi):"
    foreach ($d in $killed) { Write-Output "  - $d" }
} else {
    Write-Output "Nessun processo di AI Video Maker in esecuzione."
}
