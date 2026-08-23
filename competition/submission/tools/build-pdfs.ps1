$ErrorActionPreference = "Stop"

$ScriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$SubmissionDirectory = Split-Path -Parent $ScriptDirectory
$RepositoryRoot = Resolve-Path (Join-Path $SubmissionDirectory "..\..")
$OutputDirectory = Join-Path $SubmissionDirectory "output\pdf"
$GeneratedDirectory = Join-Path $SubmissionDirectory "typst\generated"

python (Join-Path $ScriptDirectory "assemble_documents.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $GeneratedDirectory | Out-Null

pandoc (Join-Path $GeneratedDirectory "design-body.md") -f markdown -t typst --wrap=none -o (Join-Path $GeneratedDirectory "design-body.typ")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
pandoc (Join-Path $GeneratedDirectory "test-body.md") -f markdown -t typst --wrap=none -o (Join-Path $GeneratedDirectory "test-body.typ")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$FontPath = "C:\Windows\Fonts"
typst compile --root $RepositoryRoot --font-path $FontPath (Join-Path $SubmissionDirectory "typst\design-document.typ") (Join-Path $OutputDirectory "tgoskits-competition-design-zh.pdf")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
typst compile --root $RepositoryRoot --font-path $FontPath (Join-Path $SubmissionDirectory "typst\test-report.typ") (Join-Path $OutputDirectory "tgoskits-competition-test-report-zh.pdf")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Output "PDF_BUILD_PASS count=2 output=$OutputDirectory"
