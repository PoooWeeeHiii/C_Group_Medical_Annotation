# Start the standalone DeepEdit inference service on :8010 (Windows PowerShell)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$EnvFile = Join-Path $Root ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { return }
        $key = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        Set-Item -Path "Env:$key" -Value $value
    }
}

if (-not $env:DEEPEDIT_MODEL_PATH) { $env:DEEPEDIT_MODEL_PATH = "models/deepedit/deepedit_unet.pth" }
if (-not $env:DEEPEDIT_MODEL_FORMAT) { $env:DEEPEDIT_MODEL_FORMAT = "monai_unet_checkpoint" }
if (-not $env:DEEPEDIT_CONFIG_PATH) { $env:DEEPEDIT_CONFIG_PATH = "models/deepedit/config.json" }
if (-not $env:DEEPEDIT_DEVICE) { $env:DEEPEDIT_DEVICE = "auto" }
if (-not $env:DEEPEDIT_THRESHOLD) { $env:DEEPEDIT_THRESHOLD = "0.5" }

New-Item -ItemType Directory -Force -Path (Join-Path $Root "models\deepedit") | Out-Null

$Python = $env:DEEPEDIT_PYTHON
if (-not $Python) {
    $candidates = @(
        "D:\hm_2_spleen\venv_nnunet_cpu\Scripts\python.exe",
        "D:\hm_2_spleen\venv_nnunet\Scripts\python.exe",
        (Join-Path $Root ".venv\Scripts\python.exe"),
        "python"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -eq "python" -or (Test-Path $candidate)) {
            $Python = $candidate
            break
        }
    }
}

$modelAbs = Join-Path $Root $env:DEEPEDIT_MODEL_PATH
Write-Host "[DeepEdit] PROJECT_ROOT=$Root"
Write-Host "[DeepEdit] PYTHON=$Python"
Write-Host "[DeepEdit] MODEL_PATH=$($env:DEEPEDIT_MODEL_PATH)"
Write-Host "[DeepEdit] CONFIG_PATH=$($env:DEEPEDIT_CONFIG_PATH)"
Write-Host "[DeepEdit] listening on http://127.0.0.1:8010"
Write-Host "[DeepEdit] health: curl -s http://127.0.0.1:8010/health"
if (-not (Test-Path $modelAbs) -and -not (Test-Path $env:DEEPEDIT_MODEL_PATH)) {
    Write-Host "[DeepEdit] WARNING: weight file not found. Run:"
    Write-Host "           $Python scripts\export_deepedit_init_checkpoint.py"
    Write-Host "           or scripts\train_deepedit.py"
}

& $Python -m uvicorn ai.deepedit_service:app --host 127.0.0.1 --port 8010 --reload
