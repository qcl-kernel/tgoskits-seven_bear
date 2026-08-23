#!/usr/bin/env python3
"""Build the evidence-based five-minute competition video and subtitles."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


SUBMISSION = Path(__file__).resolve().parents[1]
REPO = SUBMISSION.parents[1]
COPY = SUBMISSION / "copy"
CHARTS = SUBMISSION / "assets" / "charts"
VIDEO_ASSETS = SUBMISSION / "assets" / "video"
OUTPUT = SUBMISSION / "output" / "video"
BUILD = REPO / "tmp" / "competition-submission-build" / "video-final"
HISTORICAL_VIDEO = (
    REPO
    / "competition"
    / "results"
    / "terminal-demo-20260817"
    / "demo-terminal-5min.mp4"
)
TENNIS_VALIDATION = REPO / "apps" / "starry" / "aka00-tennis-yolo" / "validation"
STREAM_RESULT = (
    REPO
    / "apps"
    / "starry"
    / "orangepi-5-plus-uvc-rknn"
    / "images"
    / "yolov8-stream-result.png"
)

WIDTH = 1920
HEIGHT = 1080
FPS = 30
VOICE = "zh-CN-YunyangNeural"
VOICE_RATE = "+20%"
SCENE_DURATIONS = (22, 28, 36, 30, 36, 28, 34, 32, 34, 20)
HISTORICAL_STARTS = {1: 10.0, 2: 63.0, 4: 123.0}

COLORS = {
    "background": "#07111f",
    "grid": "#0d2236",
    "accent": "#28d7d0",
    "accent_soft": "#8af4ef",
    "white": "#f4f8fb",
    "muted": "#9bb0c4",
    "card": "#f7fafc",
    "card_edge": "#31536d",
    "ink": "#10263a",
    "warning": "#f2be5c",
}


@dataclass(frozen=True)
class Scene:
    index: int
    duration: int
    title: str
    caption: str
    narration: str


def main() -> int:
    require_tools("ffmpeg", "ffprobe", "wsl.exe")
    require_inputs()
    scenes = load_scenes()

    VIDEO_ASSETS.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (BUILD / "audio").mkdir(parents=True, exist_ok=True)
    (BUILD / "segments").mkdir(parents=True, exist_ok=True)

    for scene in scenes:
        image_path = VIDEO_ASSETS / f"scene-{scene.index:02d}.png"
        if scene.index in HISTORICAL_STARTS:
            render_dynamic_overlay(scene, image_path)
        else:
            render_static_scene(scene, image_path)

    audio_durations: dict[int, float] = {}
    for scene in scenes:
        audio_path = BUILD / "audio" / f"scene-{scene.index:02d}.mp3"
        synthesize_speech(scene.narration, audio_path)
        audio_durations[scene.index] = probe_duration(audio_path)
        build_segment(scene, audio_path, audio_durations[scene.index])

    master = concatenate_segments(scenes)
    subtitle_path = OUTPUT / "tgoskits-ivc-competition-demo.zh-CN.srt"
    write_subtitles(subtitle_path, scenes)
    final_path = OUTPUT / "tgoskits-ivc-competition-demo.mp4"
    mux_subtitles(master, subtitle_path, final_path)

    duration = probe_duration(final_path)
    if not math.isclose(duration, 300.0, abs_tol=0.08):
        raise RuntimeError(f"unexpected final duration: {duration:.3f}s")
    manifest = write_manifest(final_path, subtitle_path, scenes, audio_durations)
    print(
        "VIDEO_BUILD_PASS "
        f"duration={duration:.3f}s scenes={len(scenes)} "
        f"sha256={manifest['outputs']['video']['sha256']}"
    )
    return 0


def require_tools(*names: str) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise FileNotFoundError(f"missing required tools: {', '.join(missing)}")


def require_inputs() -> None:
    required = [
        COPY / "video-scenes.json",
        COPY / "video-final-corrections.json",
        HISTORICAL_VIDEO,
        STREAM_RESULT,
        Path(r"C:\Windows\Fonts\msyhbd.ttc"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing video inputs: {missing}")


def load_json(path: Path) -> dict[str, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def load_scenes() -> list[Scene]:
    copy = load_json(COPY / "video-scenes.json")
    copy.update(load_json(COPY / "video-final-corrections.json"))
    routed = load_json(COPY / "evidence-count-corrections.json")
    copy.update(
        {key.removeprefix("video__"): value for key, value in routed.items() if key.startswith("video__")}
    )
    scenes = []
    for index, duration in enumerate(SCENE_DURATIONS):
        prefix = f"{index:02d}"
        scenes.append(
            Scene(
                index=index,
                duration=duration,
                title=copy[f"{prefix}_title"],
                caption=copy[f"{prefix}_caption"],
                narration=copy[f"{prefix}_narration"],
            )
        )
    if sum(scene.duration for scene in scenes) != 300:
        raise ValueError("scene duration total must equal 300 seconds")
    return scenes


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    filename = "msyhbd.ttc" if bold else "msyh.ttc"
    return ImageFont.truetype(str(Path(r"C:\Windows\Fonts") / filename), size=size)


def base_canvas(*, transparent: bool = False) -> Image.Image:
    if transparent:
        return Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    image = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background"])
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH, 80):
        draw.line((x, 0, x, HEIGHT), fill=COLORS["grid"], width=1)
    for y in range(0, HEIGHT, 80):
        draw.line((0, y, WIDTH, y), fill=COLORS["grid"], width=1)
    draw.rectangle((0, 0, WIDTH, 8), fill=COLORS["accent"])
    return image


def text_width(draw: ImageDraw.ImageDraw, value: str, text_font: ImageFont.FreeTypeFont) -> int:
    left, _, right, _ = draw.textbbox((0, 0), value, font=text_font)
    return right - left


def wrap_pixels(
    draw: ImageDraw.ImageDraw,
    value: str,
    text_font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in value:
        candidate = current + character
        if current and text_width(draw, candidate, text_font) > max_width:
            lines.append(current)
            current = character
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def draw_header(image: Image.Image, scene: Scene, *, compact: bool = False) -> None:
    draw = ImageDraw.Draw(image)
    title_font = font(54 if compact else 58, bold=True)
    caption_font = font(28 if compact else 30)
    badge_font = font(22, bold=True)
    max_title_width = 1410
    lines = wrap_pixels(draw, scene.title, title_font, max_title_width)
    title_y = 48 if compact else 54
    for line_index, line in enumerate(lines[:2]):
        draw.text(
            (90, title_y + line_index * 67),
            line,
            font=title_font,
            fill=COLORS["white"],
        )
    caption_y = title_y + len(lines[:2]) * 67 + 4
    draw.text((92, caption_y), scene.caption, font=caption_font, fill=COLORS["accent_soft"])

    badge = f"SCENE {scene.index + 1:02d} / 10"
    badge_width = text_width(draw, badge, badge_font) + 42
    badge_box = (WIDTH - badge_width - 76, 58, WIDTH - 76, 108)
    draw.rounded_rectangle(badge_box, radius=25, fill=COLORS["accent"])
    draw.text(
        (badge_box[0] + 21, badge_box[1] + 8),
        badge,
        font=badge_font,
        fill=COLORS["background"],
    )


def draw_footer(image: Image.Image, note: str = "EVIDENCE-BASED COMPETITION DEMO") -> None:
    draw = ImageDraw.Draw(image)
    footer_font = font(20, bold=True)
    draw.line((90, 995, WIDTH - 90, 995), fill=COLORS["card_edge"], width=2)
    draw.text((92, 1014), "TGOSKits RT-IVC", font=footer_font, fill=COLORS["muted"])
    note_width = text_width(draw, note, footer_font)
    draw.text((WIDTH - 92 - note_width, 1014), note, font=footer_font, fill=COLORS["muted"])


def card(image: Image.Image, box: tuple[int, int, int, int], *, padding: int = 20) -> tuple[int, int, int, int]:
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(box, radius=26, fill=COLORS["card"], outline=COLORS["card_edge"], width=3)
    return (box[0] + padding, box[1] + padding, box[2] - padding, box[3] - padding)


def paste_contained(
    target: Image.Image,
    source_path: Path,
    box: tuple[int, int, int, int],
    *,
    background: str | None = None,
) -> None:
    with Image.open(source_path) as opened:
        source = opened.convert("RGB")
        contained = ImageOps.contain(
            source,
            (box[2] - box[0], box[3] - box[1]),
            Image.Resampling.LANCZOS,
        )
    if background:
        backing = Image.new("RGB", (box[2] - box[0], box[3] - box[1]), background)
        backing.paste(
            contained,
            ((backing.width - contained.width) // 2, (backing.height - contained.height) // 2),
        )
        contained = backing
    x = box[0] + (box[2] - box[0] - contained.width) // 2
    y = box[1] + (box[3] - box[1] - contained.height) // 2
    target.paste(contained, (x, y))


def render_static_scene(scene: Scene, output_path: Path) -> None:
    image = base_canvas()
    draw_header(image, scene)
    media_top = 220
    media_bottom = 955

    if scene.index == 0:
        inner = card(image, (130, media_top, WIDTH - 130, media_bottom), padding=30)
        paste_contained(image, CHARTS / "01-system-architecture.png", inner)
    elif scene.index == 3:
        inner = card(image, (180, media_top, WIDTH - 180, media_bottom), padding=32)
        paste_contained(image, CHARTS / "07-native-zephyr.png", inner)
    elif scene.index == 5:
        inner = card(image, (180, media_top, WIDTH - 180, media_bottom), padding=32)
        paste_contained(image, CHARTS / "04-control-effect.png", inner)
    elif scene.index == 6:
        left = card(image, (90, media_top, 1180, media_bottom), padding=24)
        right = card(image, (1210, media_top, WIDTH - 90, media_bottom), padding=20)
        paste_contained(image, CHARTS / "05-vision-loop-latency.png", left)
        paste_contained(image, STREAM_RESULT, right, background="#111820")
        draw_pill(image, (1270, 884), "VIRTUAL ACTUATOR OUTPUT", COLORS["warning"])
    elif scene.index == 7:
        left = card(image, (90, media_top, 955, media_bottom), padding=25)
        right = card(image, (985, media_top, WIDTH - 90, media_bottom), padding=25)
        paste_contained(image, CHARTS / "06-vision-optimization.png", left)
        paste_contained(image, CHARTS / "08-isolation.png", right)
    elif scene.index == 8:
        top_left = card(image, (90, media_top, 940, 610), padding=18)
        top_right = card(image, (970, media_top, WIDTH - 90, 610), padding=18)
        paste_contained(image, CHARTS / "10-labeled-pilot.png", top_left)
        paste_contained(image, CHARTS / "09-so100-id1.png", top_right)
        photos = [
            TENNIS_VALIDATION / "tennis-ball-black-box.jpg",
            TENNIS_VALIDATION / "tennis-ball-close.jpg",
            TENNIS_VALIDATION / "tennis-ball-plant.jpg",
        ]
        gap = 24
        total_width = WIDTH - 180
        photo_width = (total_width - 2 * gap) // 3
        for position, photo in enumerate(photos):
            x1 = 90 + position * (photo_width + gap)
            inner = card(image, (x1, 640, x1 + photo_width, media_bottom), padding=14)
            paste_contained(image, photo, inner, background="#111820")
        draw_pill(
            image,
            (105, 892),
            "SUPERVISED PILOT • NO CAMERA SYNC • NO RTOS MEDIATOR",
            COLORS["warning"],
        )
    elif scene.index == 9:
        left = card(image, (90, media_top, 1080, media_bottom), padding=28)
        paste_contained(image, CHARTS / "01-system-architecture.png", left)
        draw_stat_cards(image)
    else:
        raise ValueError(f"static layout is not defined for scene {scene.index}")

    draw_footer(image)
    image.save(output_path, format="PNG", optimize=True)


def draw_pill(image: Image.Image, origin: tuple[int, int], value: str, fill: str) -> None:
    draw = ImageDraw.Draw(image)
    pill_font = font(18, bold=True)
    width = text_width(draw, value, pill_font) + 34
    box = (origin[0], origin[1], origin[0] + width, origin[1] + 42)
    draw.rounded_rectangle(box, radius=20, fill=fill)
    draw.text((origin[0] + 17, origin[1] + 7), value, font=pill_font, fill=COLORS["ink"])


def draw_stat_cards(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image)
    number_font = font(62, bold=True)
    label_font = font(20, bold=True)
    stats = (
        ("21", "EVIDENCE INPUTS"),
        ("10", "GENERATED CHARTS"),
        ("2", "PDF REPORTS"),
        ("300s", "FINAL VIDEO"),
    )
    for index, (number, label) in enumerate(stats):
        column = index % 2
        row = index // 2
        x1 = 1120 + column * 355
        y1 = 285 + row * 310
        box = (x1, y1, x1 + 315, y1 + 250)
        draw.rounded_rectangle(box, radius=24, fill="#10263a", outline=COLORS["accent"], width=3)
        draw.text((x1 + 28, y1 + 38), number, font=number_font, fill=COLORS["accent_soft"])
        draw.text((x1 + 28, y1 + 145), label, font=label_font, fill=COLORS["white"])


def render_dynamic_overlay(scene: Scene, output_path: Path) -> None:
    image = base_canvas(transparent=True)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 190), fill=(7, 17, 31, 232))
    draw.rectangle((0, 815, WIDTH, HEIGHT), fill=(7, 17, 31, 238))
    draw.rectangle((0, 0, WIDTH, 8), fill=COLORS["accent"])
    draw_header(image, scene, compact=True)

    badge_font = font(18, bold=True)
    badge = "HISTORICAL TERMINAL EVIDENCE"
    width = text_width(draw, badge, badge_font) + 34
    box = (90, 842, 90 + width, 884)
    draw.rounded_rectangle(box, radius=20, fill=COLORS["warning"])
    draw.text((107, 849), badge, font=badge_font, fill=COLORS["ink"])
    boundary = "Post-hoc evidence visualization; not synchronized physical footage."
    draw.text((92, 910), boundary, font=font(25), fill=COLORS["white"])
    draw.text((92, 960), "TGOSKits RT-IVC", font=font(20, bold=True), fill=COLORS["muted"])
    image.save(output_path, format="PNG", optimize=True)


def synthesize_speech(text: str, output_path: Path) -> None:
    text_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    digest_path = output_path.with_suffix(output_path.suffix + ".sha256")
    if (
        output_path.is_file()
        and output_path.stat().st_size > 2048
        and digest_path.is_file()
        and digest_path.read_text(encoding="ascii").strip() == text_digest
    ):
        return
    output_path.unlink(missing_ok=True)
    digest_path.unlink(missing_ok=True)
    command = [
        "wsl.exe",
        "-e",
        "/home/seven_wsl/.local/bin/edge-tts",
        "--voice",
        VOICE,
        "--rate",
        VOICE_RATE,
        "--text",
        text,
        "--write-media",
        wsl_path(output_path),
    ]
    run(command)
    if not output_path.is_file() or output_path.stat().st_size <= 2048:
        raise RuntimeError(f"speech synthesis produced no usable audio: {output_path}")
    digest_path.write_text(text_digest + "\n", encoding="ascii", newline="\n")


def wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    tail = resolved.as_posix().split(":", 1)[1]
    return f"/mnt/{drive}{tail}"


def probe_duration(path: Path) -> float:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture=True,
    )
    return float(result.stdout.strip())


def atempo_chain(tempo: float) -> str:
    if tempo <= 0:
        raise ValueError("tempo must be positive")
    factors: list[float] = []
    while tempo < 0.5:
        factors.append(0.5)
        tempo /= 0.5
    while tempo > 2.0:
        factors.append(2.0)
        tempo /= 2.0
    factors.append(tempo)
    return ",".join(f"atempo={factor:.6f}" for factor in factors)


def build_segment(scene: Scene, audio_path: Path, raw_audio_duration: float) -> None:
    output_path = BUILD / "segments" / f"scene-{scene.index:02d}.mp4"
    frame_path = VIDEO_ASSETS / f"scene-{scene.index:02d}.png"
    audio_target = scene.duration - 1.0
    tempo = raw_audio_duration / audio_target
    audio_filter = (
        f"{atempo_chain(tempo)},"
        "loudnorm=I=-18:LRA=9:TP=-1.5,"
        "adelay=500|500,"
        f"apad,atrim=0:{scene.duration},"
        f"afade=t=in:st=0:d=0.25,afade=t=out:st={scene.duration - 0.55}:d=0.45[a]"
    )
    fade_out = scene.duration - 0.4

    if scene.index in HISTORICAL_STARTS:
        command = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{HISTORICAL_STARTS[scene.index]:.3f}",
            "-i",
            str(HISTORICAL_VIDEO),
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-i",
            str(frame_path),
            "-i",
            str(audio_path),
            "-filter_complex",
            (
                f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=0x07111f[base];"
                "[1:v]format=rgba[overlay];"
                "[base][overlay]overlay=0:0:shortest=0,"
                f"fade=t=in:st=0:d=0.35,fade=t=out:st={fade_out}:d=0.4,"
                "format=yuv420p[v];"
                f"[2:a]{audio_filter}"
            ),
        ]
    else:
        command = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-i",
            str(frame_path),
            "-i",
            str(audio_path),
            "-filter_complex",
            (
                f"[0:v]scale={WIDTH}:{HEIGHT},"
                f"fade=t=in:st=0:d=0.35,fade=t=out:st={fade_out}:d=0.4,"
                "format=yuv420p[v];"
                f"[1:a]{audio_filter}"
            ),
        ]

    command.extend(
        [
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            str(scene.duration),
            "-r",
            str(FPS),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    run(command)


def concatenate_segments(scenes: list[Scene]) -> Path:
    concat_path = BUILD / "concat.txt"
    lines = []
    for scene in scenes:
        segment = (BUILD / "segments" / f"scene-{scene.index:02d}.mp4").resolve()
        escaped = segment.as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    master = BUILD / "master.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(master),
        ]
    )
    return master


def subtitle_chunks(value: str, limit: int = 36) -> list[str]:
    clauses = [part.strip() for part in re.findall(r"[^。！？；]+[。！？；]?", value) if part.strip()]
    chunks: list[str] = []
    for clause in clauses:
        while len(clause) > limit:
            split = max(clause.rfind(mark, 0, limit + 1) for mark in ("，", "、", ",", " "))
            if split < limit // 2:
                split = limit
            else:
                split += 1
            chunks.append(clause[:split].strip())
            clause = clause[split:].strip()
        if clause:
            chunks.append(clause)
    return chunks


def write_subtitles(path: Path, scenes: list[Scene]) -> None:
    blocks: list[str] = []
    sequence = 1
    scene_start = 0.0
    for scene in scenes:
        chunks = subtitle_chunks(scene.narration)
        weights = [max(1, len(re.sub(r"\s+", "", chunk))) for chunk in chunks]
        available = scene.duration - 1.2
        cursor = scene_start + 0.6
        total_weight = sum(weights)
        for chunk, weight in zip(chunks, weights, strict=True):
            duration = available * weight / total_weight
            end = cursor + duration
            blocks.append(
                f"{sequence}\n{srt_time(cursor)} --> {srt_time(end)}\n{chunk}\n"
            )
            sequence += 1
            cursor = end
        scene_start += scene.duration
    path.write_text("\n".join(blocks), encoding="utf-8-sig", newline="\n")


def srt_time(value: float) -> str:
    milliseconds = round(value * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def mux_subtitles(master: Path, subtitles: Path, output_path: Path) -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(master),
            "-i",
            str(subtitles),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-map",
            "1:0",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-c:s",
            "mov_text",
            "-metadata:s:s:0",
            "language=zho",
            "-metadata:s:s:0",
            "title=Chinese (Simplified)",
            "-t",
            "300",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(REPO.resolve()).as_posix()


def write_manifest(
    video: Path,
    subtitles: Path,
    scenes: list[Scene],
    audio_durations: dict[int, float],
) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema_version": 1,
        "generator": relative(Path(__file__)),
        "voice": {"provider": "Microsoft Edge TTS", "name": VOICE, "rate": VOICE_RATE},
        "historical_source": {
            "path": relative(HISTORICAL_VIDEO),
            "sha256": sha256(HISTORICAL_VIDEO),
            "disclosure": "Post-hoc evidence visualization; not synchronized physical footage.",
        },
        "scenes": [
            {
                "index": scene.index,
                "duration_seconds": scene.duration,
                "title": scene.title,
                "narration_sha256": hashlib.sha256(scene.narration.encode("utf-8")).hexdigest(),
                "raw_audio_seconds": round(audio_durations[scene.index], 3),
                "historical_source_start_seconds": HISTORICAL_STARTS.get(scene.index),
            }
            for scene in scenes
        ],
        "outputs": {
            "video": {"path": relative(video), "sha256": sha256(video), "duration_seconds": 300.0},
            "subtitles": {"path": relative(subtitles), "sha256": sha256(subtitles)},
        },
        "limitations": [
            "No synchronized physical camera-to-arm footage is claimed.",
            "SO-100 evidence is a supervised single-joint pilot without an RTOS mediator.",
            "Continuous-loop actuator output is virtual state only.",
        ],
    }
    path = OUTPUT / "video-manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
