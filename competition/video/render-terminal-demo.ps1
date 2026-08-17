[CmdletBinding()]
param(
    [string]$Voice = "zh-CN-YunxiNeural",
    [string]$OutputPath = "",
    [string]$WslDistro = "Ubuntu",
    [string]$VhsImage = "ghcr.io/charmbracelet/vhs@sha256:9d5fc3dc0c160b0fb1d2212baff07e6bdf3fa9438c504a3237484567302fcf93",
    [switch]$ReuseCaptures,
    [switch]$ReuseNarration
)

$ErrorActionPreference = "Stop"
$scriptRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $scriptRoot "../..")).Path
$resultRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $repoRoot "competition/results/terminal-demo-20260817")
)
if (-not $OutputPath) {
    $OutputPath = Join-Path $resultRoot "demo-terminal-5min.mp4"
}
$outputFullPath = [System.IO.Path]::GetFullPath($OutputPath)
$resultPrefix = $resultRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) +
    [System.IO.Path]::DirectorySeparatorChar
if (-not $outputFullPath.StartsWith(
        $resultPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Output must stay inside $resultRoot"
}

$ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source
$ffprobe = (Get-Command ffprobe -ErrorAction Stop).Source
$python = (Get-Command python -ErrorAction Stop).Source
$wsl = (Get-Command wsl.exe -ErrorAction Stop).Source
$timelinePath = Join-Path $scriptRoot "terminal-timeline.json"
$narrationSourcePath = Join-Path $scriptRoot "terminal-narration.json"
$overlayPath = Join-Path $scriptRoot "terminal-demo.ass"
$buildRoot = Join-Path $scriptRoot "build"
$rawRoot = Join-Path $buildRoot "raw"
$normalizedRoot = Join-Path $buildRoot "normalized"
$audioRoot = Join-Path $buildRoot "audio"

function Invoke-Render {
    $timeline = Get-Content -LiteralPath $timelinePath -Raw -Encoding utf8 |
        ConvertFrom-Json
    $narration = Get-Content -LiteralPath $narrationSourcePath -Raw -Encoding utf8 |
        ConvertFrom-Json
    Assert-Timeline $timeline $narration

    New-Item -ItemType Directory -Force -Path @(
        $resultRoot,
        $buildRoot,
        $rawRoot,
        $normalizedRoot,
        $audioRoot
    ) | Out-Null

    $repoWslPath = ConvertTo-WslPath $repoRoot

    & $wsl -d $WslDistro -- docker image inspect $VhsImage 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Missing VHS image. Run: wsl -d $WslDistro -- docker pull $VhsImage"
    }

    if (-not $ReuseCaptures) {
        Render-TerminalCaptures $timeline $repoWslPath
    } else {
        Assert-CapturesExist $timeline
    }

    $segmentPaths = Render-NormalizedSegments $timeline
    $videoConcatPath = Write-ConcatList $segmentPaths (Join-Path $buildRoot "video-concat.txt")
    $silentTimelinePath = Join-Path $buildRoot "silent-timeline.mp4"
    & $ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i $videoConcatPath `
        -an -c copy -movflags +faststart $silentTimelinePath
    if ($LASTEXITCODE -ne 0) {
        throw "Video timeline concatenation failed"
    }

    $narrationPath = Join-Path $buildRoot "narration.wav"
    if (-not $ReuseNarration) {
        $wavPaths = Render-Narration $narration
        $audioConcatPath = Write-ConcatList $wavPaths (Join-Path $buildRoot "audio-concat.txt")
        & $ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i $audioConcatPath `
            -c:a pcm_s16le $narrationPath
        if ($LASTEXITCODE -ne 0) {
            throw "Narration concatenation failed"
        }
    } elseif (-not (Test-Path -LiteralPath $narrationPath -PathType Leaf)) {
        throw "-ReuseNarration was requested, but $narrationPath is missing"
    }

    Push-Location $scriptRoot
    try {
        & $ffmpeg -hide_banner -loglevel warning -y `
            -i $silentTimelinePath `
            -i $narrationPath `
            -vf "drawbox=x=0:y=0:w=iw:h=7:color=0x4fddd5:t=fill,drawbox=x=0:y=713:w=iw:h=7:color=0x142337:t=fill,ass=terminal-demo.ass" `
            -map 0:v:0 -map 1:a:0 -t 300 `
            -c:v libx264 -preset medium -crf 20 -r 30 -pix_fmt yuv420p `
            -c:a aac -b:a 112k -ar 48000 -ac 1 -movflags +faststart `
            $outputFullPath
        if ($LASTEXITCODE -ne 0) {
            throw "Final video rendering failed"
        }
    } finally {
        Pop-Location
    }

    Write-DeliveryMetadata $timeline $outputFullPath
    & $ffprobe -v error `
        -show_entries format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels `
        -of json $outputFullPath
}

function Render-TerminalCaptures {
    param(
        [object[]]$Segments,
        [string]$RepoWslPath
    )

    $terminalSegments = @($Segments | Where-Object { $_.kind -eq "terminal" })
    foreach ($segment in $terminalSegments) {
        $tapeRelative = "competition/video/tapes/$($segment.tape)"
        $rawRelative = "competition/video/build/raw/$($segment.id).mp4"
        $rawPath = Join-Path $rawRoot "$($segment.id).mp4"
        Write-Host ("Recording terminal scene: {0}" -f $segment.id) -ForegroundColor Cyan
        & $wsl -d $WslDistro -- docker run --rm `
            -v "${RepoWslPath}:/vhs" `
            -w /vhs `
            $VhsImage `
            $tapeRelative `
            -o "/vhs/$rawRelative"
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $rawPath -PathType Leaf)) {
            throw "VHS capture failed for $($segment.id)"
        }
    }
}

function Assert-CapturesExist {
    param([object[]]$Segments)

    foreach ($segment in @($Segments | Where-Object { $_.kind -eq "terminal" })) {
        $rawPath = Join-Path $rawRoot "$($segment.id).mp4"
        if (-not (Test-Path -LiteralPath $rawPath -PathType Leaf)) {
            throw "Missing reusable VHS capture: $rawPath"
        }
    }
}

function Render-NormalizedSegments {
    param([object[]]$Segments)

    $rendered = @()
    foreach ($segment in $Segments) {
        $duration = [double]$segment.duration_seconds
        $durationText = Format-Decimal $duration
        $segmentPath = Join-Path $normalizedRoot "$($segment.id).mp4"
        if ($segment.kind -eq "card") {
            $cardInput = "color=c=0x07111f:s=1280x720:r=30:d=$durationText"
            $cardFilter = "drawgrid=w=80:h=80:t=1:c=0x142337@0.32,drawbox=x=0:y=0:w=iw:h=7:color=0x4fddd5:t=fill,drawbox=x=0:y=713:w=iw:h=7:color=0x142337:t=fill,format=yuv420p"
            & $ffmpeg -hide_banner -loglevel error -y `
                -f lavfi -i $cardInput -vf $cardFilter -an `
                -c:v libx264 -preset veryfast -crf 18 -r 30 `
                -video_track_timescale 90000 $segmentPath
        } else {
            $rawPath = Join-Path $rawRoot "$($segment.id).mp4"
            $speed = [double]$segment.speed
            $speedText = Format-Decimal $speed
            $terminalFilter = "setpts=PTS/$speedText,fps=30,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x07111f,tpad=stop_mode=clone:stop_duration=$durationText,trim=duration=$durationText,setpts=PTS-STARTPTS,format=yuv420p"
            & $ffmpeg -hide_banner -loglevel error -y -i $rawPath `
                -vf $terminalFilter -an `
                -c:v libx264 -preset veryfast -crf 18 -r 30 `
                -video_track_timescale 90000 $segmentPath
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Segment normalization failed for $($segment.id)"
        }
        $rendered += $segmentPath
    }
    return $rendered
}

function Render-Narration {
    param([object[]]$Segments)

    $rendered = @()
    for ($index = 0; $index -lt $Segments.Count; $index++) {
        $segment = $Segments[$index]
        $number = "{0:D2}" -f ($index + 1)
        $mp3Path = Join-Path $audioRoot "$number-$($segment.id).mp3"
        $wavPath = Join-Path $audioRoot "$number-$($segment.id).wav"
        $duration = [double]$segment.duration_seconds
        $durationText = Format-Decimal $duration

        & $python -m edge_tts --voice $Voice --rate=-4% --text $segment.text `
            --write-media $mp3Path
        if ($LASTEXITCODE -ne 0) {
            throw "Speech synthesis failed for $($segment.id)"
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
            if ($tempo -gt 1.2) {
                throw "Narration $($segment.id) is too dense for its scene (atempo $tempo)"
            }
            $tempoText = Format-Decimal $tempo
            $audioFilter = "atempo=$tempoText,apad,atrim=duration=$durationText"
        } else {
            $audioFilter = "apad,atrim=duration=$durationText"
        }
        & $ffmpeg -hide_banner -loglevel error -y -i $mp3Path `
            -af $audioFilter -ar 48000 -ac 1 -c:a pcm_s16le $wavPath
        if ($LASTEXITCODE -ne 0) {
            throw "Audio normalization failed for $($segment.id)"
        }
        $rendered += $wavPath
    }
    return $rendered
}

function Assert-Timeline {
    param(
        [object[]]$TimelineSegments,
        [object[]]$NarrationSegments
    )

    $totalDuration = ($TimelineSegments |
            Measure-Object -Property duration_seconds -Sum).Sum
    if ($totalDuration -ne 300) {
        throw "Timeline must total exactly 300 seconds; got $totalDuration"
    }
    if ($TimelineSegments.Count -ne $NarrationSegments.Count) {
        throw "Timeline and narration segment counts differ"
    }
    for ($index = 0; $index -lt $TimelineSegments.Count; $index++) {
        $videoSegment = $TimelineSegments[$index]
        $audioSegment = $NarrationSegments[$index]
        if ($videoSegment.id -ne $audioSegment.id -or
            $videoSegment.duration_seconds -ne $audioSegment.duration_seconds) {
            throw "Timeline/narration mismatch at segment $index"
        }
        if ($videoSegment.kind -notin @("card", "terminal")) {
            throw "Unsupported segment kind: $($videoSegment.kind)"
        }
        if ($videoSegment.kind -eq "terminal") {
            if (-not $videoSegment.tape -or [double]$videoSegment.speed -lt 1) {
                throw "Invalid terminal segment: $($videoSegment.id)"
            }
            $tapePath = Join-Path $scriptRoot "tapes/$($videoSegment.tape)"
            if (-not (Test-Path -LiteralPath $tapePath -PathType Leaf)) {
                throw "Missing VHS tape: $tapePath"
            }
        }
    }
    if (-not (Test-Path -LiteralPath $overlayPath -PathType Leaf)) {
        throw "Missing ASS overlay: $overlayPath"
    }
}

function Write-ConcatList {
    param(
        [string[]]$Paths,
        [string]$ListPath
    )

    $lines = $Paths | ForEach-Object {
        "file '" + $_.Replace("\", "/").Replace("'", "'\''") + "'"
    }
    [System.IO.File]::WriteAllLines(
        $ListPath,
        $lines,
        [System.Text.UTF8Encoding]::new($false)
    )
    return $ListPath
}

function Write-DeliveryMetadata {
    param(
        [object[]]$Segments,
        [string]$VideoPath
    )

    $probeJson = & $ffprobe -v error `
        -show_entries format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels `
        -of json $VideoPath
    if ($LASTEXITCODE -ne 0) {
        throw "FFprobe validation failed"
    }
    [System.IO.File]::WriteAllText(
        (Join-Path $resultRoot "ffprobe.json"),
        ($probeJson -join [Environment]::NewLine) + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )

    $videoHash = (Get-FileHash -LiteralPath $VideoPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $videoName = Split-Path $VideoPath -Leaf
    [System.IO.File]::WriteAllText(
        (Join-Path $resultRoot "SHA256SUMS"),
        "$videoHash  $videoName`n",
        [System.Text.UTF8Encoding]::new($false)
    )

    $evidenceFiles = @(
        "competition/results/current-source-smoke-20260813/provenance.json",
        "competition/results/current-source-smoke-20260813/ivc/console.log",
        "competition/results/current-source-smoke-20260813/ivc/summary.json",
        "competition/results/current-source-smoke-20260813/rt/comparison.json",
        "competition/results/axvisor-rt-formal-20260816/campaign-summary.json"
    )
    $evidenceHashes = [ordered]@{}
    foreach ($relativePath in $evidenceFiles) {
        $fullPath = Join-Path $repoRoot $relativePath
        $evidenceHashes[$relativePath] = (
            Get-FileHash -LiteralPath $fullPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
    }
    $sourceHead = (& git -C $repoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to record source HEAD"
    }
    $sourceStatus = @(
        & git -C $repoRoot status --porcelain=v1 -- . `
            ":(exclude)competition/results/terminal-demo-20260817" `
            ":(exclude)competition/video/build"
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to record source worktree status"
    }

    $productionFiles = @(
        "competition/video/render-terminal-demo.ps1",
        "competition/video/show-evidence.ps1",
        "competition/video/show-evidence.py",
        "competition/video/terminal-demo.ass",
        "competition/video/terminal-narration.json",
        "competition/video/terminal-timeline.json",
        "competition/video/tapes/architecture.tape",
        "competition/video/tapes/rt-mechanism.tape",
        "competition/video/tapes/rt-results.tape",
        "competition/video/tapes/rt-baseline.tape",
        "competition/video/tapes/network-protocol.tape",
        "competition/video/tapes/ivc-log.tape",
        "competition/video/tapes/ivc-analysis.tape",
        "competition/video/tapes/ai-loop.tape",
        "competition/video/tapes/ai-results.tape",
        "competition/video/tapes/verify.tape"
    )
    $productionHashes = [ordered]@{}
    foreach ($relativePath in $productionFiles) {
        $fullPath = Join-Path $repoRoot $relativePath
        $productionHashes[$relativePath] = (
            Get-FileHash -LiteralPath $fullPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
    }

    $manifest = [ordered]@{
        schema_version = 1
        generated_at_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
        source_head = $sourceHead
        source_worktree_dirty = ($sourceStatus.Count -gt 0)
        output = [ordered]@{
            path = "competition/results/terminal-demo-20260817/$videoName"
            sha256 = $videoHash
            duration_seconds = 300
            width = 1280
            height = 720
            video_codec = "h264"
            audio_codec = "aac"
        }
        recording = [ordered]@{
            terminal_recorder = "VHS official container"
            vhs_image = $VhsImage
            shell = "bash"
            raw_capture_speed = 1
            accelerated_segments = @(
                $Segments |
                    Where-Object { $_.kind -eq "terminal" -and [double]$_.speed -gt 1 } |
                    ForEach-Object {
                        [ordered]@{
                            id = $_.id
                            final_speed = [double]$_.speed
                        }
                    }
            )
        }
        production_input_sha256 = $productionHashes
        evidence_sha256 = $evidenceHashes
    }
    $manifestJson = $manifest | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText(
        (Join-Path $resultRoot "video-manifest.json"),
        $manifestJson + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Format-Decimal {
    param([double]$Value)

    return $Value.ToString(
        "0.######",
        [System.Globalization.CultureInfo]::InvariantCulture
    )
}

function ConvertTo-WslPath {
    param([string]$WindowsPath)

    $fullPath = [System.IO.Path]::GetFullPath($WindowsPath)
    if ($fullPath -notmatch "^([A-Za-z]):\\(.*)$") {
        throw "Only drive-letter paths can be mapped into WSL: $fullPath"
    }
    $drive = $Matches[1].ToLowerInvariant()
    $relativePath = $Matches[2].Replace("\", "/")
    return "/mnt/$drive/$relativePath"
}

Invoke-Render
