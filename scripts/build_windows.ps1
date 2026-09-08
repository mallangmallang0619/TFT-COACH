param([string]$TesseractDirectory = 'C:\Program Files\Tesseract-OCR')
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Push-Location $project
try {
    if (-not (Test-Path "$TesseractDirectory\tesseract.exe")) { throw 'Install Tesseract or provide -TesseractDirectory.' }
    if (-not (Test-Path "$TesseractDirectory\tessdata\eng.traineddata")) { throw 'English Tesseract data is required.' }
    if (-not (Test-Path 'packaging/.venv/Scripts/python.exe')) {
        python -m venv packaging/.venv
        if ($LASTEXITCODE) { throw 'Could not create build environment.' }
    }
    & packaging/.venv/Scripts/python.exe -m pip install -r packaging/requirements-build.txt
    if ($LASTEXITCODE) { throw 'Build dependency installation failed.' }
    New-Item -ItemType Directory -Force packaging/tesseract/tessdata | Out-Null
    Get-ChildItem -LiteralPath $TesseractDirectory -Filter '*.dll' | Copy-Item -Destination packaging/tesseract
    Copy-Item -LiteralPath "$TesseractDirectory\tesseract.exe" -Destination packaging/tesseract
    Copy-Item -LiteralPath "$TesseractDirectory\tessdata\eng.traineddata" -Destination packaging/tesseract/tessdata
    if (Test-Path "$TesseractDirectory\doc") { Copy-Item -LiteralPath "$TesseractDirectory\doc" -Destination packaging/tesseract -Recurse -Force }
    & packaging/.venv/Scripts/python.exe -m PyInstaller --noconfirm --distpath packaging/dist --workpath packaging/build packaging/backend.spec
    if ($LASTEXITCODE) { throw 'Backend packaging failed.' }
} finally { Pop-Location }
