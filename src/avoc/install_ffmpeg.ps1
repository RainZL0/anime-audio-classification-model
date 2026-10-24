# Installs FFmpeg with Scoop, and Scoop itself first when it is missing. Both go into the user's
# own folder, so no administrator rights are needed. The app runs this when the person clicks
# "Install it for me in one click"; it can also be run by hand:
#   powershell -ExecutionPolicy Bypass -File install_ffmpeg.ps1
# The last line it prints is SHIMS=<folder>: the folder to add to PATH, where ffmpeg now is.

$ErrorActionPreference = 'Stop'
$root = if ($env:SCOOP) { $env:SCOOP } else { Join-Path $HOME 'scoop' }
$shims = Join-Path $root 'shims'
$scoop = Join-Path $shims 'scoop.ps1'

if (Test-Path $scoop) {
    Write-Output "Scoop is already here: $root"
} else {
    Write-Output 'Installing Scoop from https://get.scoop.sh ...'
    # The same two lines as on https://scoop.sh. The policy lets the user's own scripts run, which
    # Scoop needs later in a normal terminal; a company policy may forbid changing it, which is fine.
    try {
        Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
    } catch {
        Write-Output "Could not change the execution policy: $($_.Exception.Message)"
    }
    Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression
    if (-not (Test-Path $scoop)) { throw 'Scoop was not installed; see the lines above.' }
}

Write-Output 'Installing FFmpeg with Scoop ...'
& $scoop install ffmpeg
if (-not (Test-Path (Join-Path $shims 'ffmpeg.exe'))) {
    throw 'FFmpeg was not installed; see the lines above.'
}
Write-Output "SHIMS=$shims"
