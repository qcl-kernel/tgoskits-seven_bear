[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet(
        "Source",
        "Config",
        "IvcCommand",
        "IvcLog",
        "IvcAnalysis",
        "RtCurrent",
        "RtFormal",
        "AiReliability",
        "Verify"
    )]
    [string]$Scene,

    [ValidateRange(0, 10000)]
    [int]$DelayMs = 350
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "show-evidence.py"
& python $scriptPath $Scene.ToLowerInvariant() --delay-ms $DelayMs
if ($LASTEXITCODE -ne 0) {
    throw "Evidence scene '$Scene' exited with $LASTEXITCODE"
}
