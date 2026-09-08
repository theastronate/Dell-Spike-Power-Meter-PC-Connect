$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Create it with: py -m venv .venv"
}

& $python -m pip install -r (Join-Path $projectRoot "requirements-build.txt")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath (Join-Path $projectRoot "dist") `
    --workpath (Join-Path $projectRoot "build\pyinstaller") `
    (Join-Path $projectRoot "DellPowerMeter.spec")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$settingsPath = Join-Path $projectRoot "dist\dpm_ui.ini"
if (-not (Test-Path -LiteralPath $settingsPath)) {
    $sourceSettings = Join-Path $projectRoot "src\dpm_ui.ini"
    if (Test-Path -LiteralPath $sourceSettings) {
        Copy-Item -LiteralPath $sourceSettings -Destination $settingsPath
    } else {
        Set-Content -LiteralPath $settingsPath -Encoding ASCII -Value @(
            "[window]", "width = 920", "height = 980", "maximized = False"
        )
    }
}

Write-Host "Built: $projectRoot\dist\Spike Power Meter.exe"
Write-Host "Window settings: $settingsPath"
