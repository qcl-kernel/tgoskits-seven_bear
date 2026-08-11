[CmdletBinding()]
param(
    [string]$Voice = "zh-CN-YunxiNeural",
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$scriptRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $scriptRoot "../..")).Path
if (-not $OutputPath) {
    $OutputPath = Join-Path $repoRoot "competition/results/current-source-smoke-20260812/demo-5min.mp4"
}
$outputFullPath = [System.IO.Path]::GetFullPath($OutputPath)
$evidenceRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $repoRoot "competition/results/current-source-smoke-20260812")
)
if (-not $outputFullPath.StartsWith($evidenceRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Output must stay inside $evidenceRoot"
}

$ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source
$ffprobe = (Get-Command ffprobe -ErrorAction Stop).Source
$segments = Get-Content -Raw -Encoding UTF8 (Join-Path $scriptRoot "narration.json") |
    ConvertFrom-Json
$totalDuration = ($segments | Measure-Object -Property duration_seconds -Sum).Sum
if ($totalDuration -ne 300) {
    throw "Narration timeline must total exactly 300 seconds; got $totalDuration"
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
    "tgoskits-demo-" + [System.Guid]::NewGuid().ToString("N")
)
New-Item -ItemType Directory -Path $tempRoot | Out-Null

try {
    $wavPaths = @()
    for ($index = 0; $index -lt $segments.Count; $index++) {
        $number = "{0:D2}" -f ($index + 1)
        $mp3Path = Join-Path $tempRoot "$number.mp3"
        $wavPath = Join-Path $tempRoot "$number.wav"
        $duration = [double]$segments[$index].duration_seconds

        & python -m edge_tts --voice $Voice --rate=-4% --text $segments[$index].text `
            --write-media $mp3Path
        if ($LASTEXITCODE -ne 0) {
            throw "Speech synthesis failed for segment $number"
        }

        $rawDurationText = & $ffprobe -v error -show_entries format=duration `
            -of default=noprint_wrappers=1:nokey=1 $mp3Path
        $rawDuration = [double]::Parse(
            $rawDurationText.Trim(),
            [System.Globalization.CultureInfo]::InvariantCulture
        )
        $targetSpeechDuration = $duration - 0.75
        if ($rawDuration -gt $targetSpeechDuration) {
            $tempo = $rawDuration / $targetSpeechDuration
            if ($tempo -gt 2.0) {
                throw "Segment $number requires unsupported atempo $tempo"
            }
            $tempoText = $tempo.ToString("0.000000", [System.Globalization.CultureInfo]::InvariantCulture)
            $audioFilter = "atempo=$tempoText,apad,atrim=duration=$duration"
        } else {
            $audioFilter = "apad,atrim=duration=$duration"
        }

        & $ffmpeg -hide_banner -loglevel error -y -i $mp3Path -af $audioFilter `
            -ar 48000 -ac 1 -c:a pcm_s16le $wavPath
        if ($LASTEXITCODE -ne 0) {
            throw "Audio normalization failed for segment $number"
        }
        $wavPaths += $wavPath
    }

    $concatPath = Join-Path $tempRoot "audio-concat.txt"
    $concatLines = $wavPaths | ForEach-Object {
        "file '" + $_.Replace("\", "/").Replace("'", "'\''") + "'"
    }
    [System.IO.File]::WriteAllLines(
        $concatPath,
        $concatLines,
        [System.Text.UTF8Encoding]::new($false)
    )
    $narrationPath = Join-Path $tempRoot "narration.wav"
    & $ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i $concatPath `
        -c:a pcm_s16le $narrationPath
    if ($LASTEXITCODE -ne 0) {
        throw "Narration concatenation failed"
    }

    New-Item -ItemType Directory -Force -Path (Split-Path $outputFullPath) | Out-Null
    Push-Location $scriptRoot
    try {
        & $ffmpeg -hide_banner -loglevel warning -y `
            -f lavfi -i "color=c=0x07111f:s=1280x720:r=30:d=300" `
            -i $narrationPath `
            -vf "drawbox=x=0:y=0:w=iw:h=8:color=0x4fddd5:t=fill,drawbox=x=0:y=712:w=iw:h=8:color=0x1b2a40:t=fill,ass=demo-5min.ass" `
            -map 0:v:0 -map 1:a:0 -t 300 -c:v libx264 -preset medium -crf 20 `
            -pix_fmt yuv420p -c:a aac -b:a 96k -movflags +faststart $outputFullPath
        if ($LASTEXITCODE -ne 0) {
            throw "Video rendering failed"
        }
    } finally {
        Pop-Location
    }
} finally {
    $resolvedTemp = [System.IO.Path]::GetFullPath($tempRoot)
    $systemTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if ($resolvedTemp.StartsWith($systemTemp, [System.StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path $resolvedTemp -Leaf).StartsWith("tgoskits-demo-")) {
        Remove-Item -LiteralPath $resolvedTemp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

& $ffprobe -v error -show_entries format=duration,size:stream=codec_name,width,height,r_frame_rate `
    -of json $outputFullPath
