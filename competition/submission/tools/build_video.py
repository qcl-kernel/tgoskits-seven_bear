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
TERMINAL_VIDEO = (
    REPO
    / "competition"
    / "results"
    / "terminal-demo-20260817"
    / "demo-terminal-5min.mp4"
)
LIVE_CAMERA_DIR = VIDEO_ASSETS / "live-camera"
LIVE_CAMERA_VIDEO = LIVE_CAMERA_DIR / "orange-pi-uvc-live-20260824.mp4"
LIVE_CAMERA_METADATA = LIVE_CAMERA_DIR / "capture-metadata.json"

WIDTH = 1920
HEIGHT = 1080
FPS = 30
VOICE = "zh-CN-YunyangNeural"
VOICE_RATE = "+20%"
SCENE_DURATIONS = (22, 28, 36, 30, 36, 28, 34, 32, 34, 20)
TERMINAL_STARTS = {1: 10.0, 2: 63.0, 4: 123.0}
TERMINAL_SCENES = frozenset(TERMINAL_STARTS)
LIVE_CAMERA_STARTS = {6: 0.0, 8: 6.0}
LIVE_CAMERA_SCENES = frozenset(LIVE_CAMERA_STARTS)

# All dynamic footage stays inside the projector-safe region.  The terminal
# crop focuses on the source recording's useful top 500 rows before scaling.
TERMINAL_MEDIA_BOX = (170, 215, 1750, 915)
TERMINAL_CONTENT_BOX = (194, 275, 1726, 891)
LIVE_CAMERA_CONTENT_BOXES = {
    6: (116, 270, 1216, 888),
    8: (116, 270, 1116, 832),
}

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
        if scene_media_kind(scene.index) == "terminal":
            render_terminal_frame(scene, image_path)
        elif scene_media_kind(scene.index) == "live-camera":
            render_live_camera_frame(scene, image_path)
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
        TERMINAL_VIDEO,
        LIVE_CAMERA_VIDEO,
        LIVE_CAMERA_METADATA,
        Path(r"C:\Windows\Fonts\msyhbd.ttc"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing video inputs: {missing}")
    metadata = json.loads(LIVE_CAMERA_METADATA.read_text(encoding="utf-8"))
    if metadata.get("video_sha256") != sha256(LIVE_CAMERA_VIDEO):
        raise RuntimeError("live camera video does not match its recorded SHA-256")
    if metadata.get("framing_approved") is not True:
        reason = metadata.get("framing_rejection_reason", "no rejection reason recorded")
        raise RuntimeError(f"live camera framing is not approved: {reason}")


def load_json(path: Path) -> dict[str, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def load_scenes() -> list[Scene]:
    copy = load_json(COPY / "video-scenes.json")
    routed = load_json(COPY / "evidence-count-corrections.json")
    copy.update(
        {key.removeprefix("video__"): value for key, value in routed.items() if key.startswith("video__")}
    )
    copy.update(load_json(COPY / "video-final-corrections.json"))
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


def scene_media_kind(index: int) -> str:
    if index in TERMINAL_SCENES:
        return "terminal"
    if index in LIVE_CAMERA_SCENES:
        return "live-camera"
    return "static"


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
    elif scene.index == 7:
        left = card(image, (90, media_top, 955, media_bottom), padding=25)
        right = card(image, (985, media_top, WIDTH - 90, media_bottom), padding=25)
        paste_contained(image, CHARTS / "06-vision-optimization.png", left)
        paste_contained(image, CHARTS / "08-isolation.png", right)
    elif scene.index == 9:
        left = card(image, (90, media_top, 1080, media_bottom), padding=28)
        paste_contained(image, CHARTS / "01-system-architecture.png", left)
        draw_system_stat_cards(image)
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


def draw_system_stat_cards(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image)
    number_font = font(62, bold=True)
    label_font = font(20, bold=True)
    stats = (
        ("5", "RT AB/BA PAIRS"),
        ("10,000", "SAMPLES / HALF"),
        ("60/60", "IVC ACTIONS APPLIED"),
        ("1×", "SO-100 ID1 CYCLE"),
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


def render_terminal_frame(scene: Scene, output_path: Path) -> None:
    image = base_canvas()
    draw = ImageDraw.Draw(image)
    draw_header(image, scene, compact=True)
    draw.rounded_rectangle(
        TERMINAL_MEDIA_BOX,
        radius=24,
        fill="#020b16",
        outline=COLORS["accent"],
        width=3,
    )
    draw.rectangle(
        (
            TERMINAL_MEDIA_BOX[0] + 3,
            TERMINAL_MEDIA_BOX[1] + 3,
            TERMINAL_MEDIA_BOX[2] - 3,
            TERMINAL_CONTENT_BOX[1] - 5,
        ),
        fill="#10263a",
    )
    draw.text(
        (TERMINAL_MEDIA_BOX[0] + 24, TERMINAL_MEDIA_BOX[1] + 14),
        "ARCHIVED TERMINAL EVIDENCE",
        font=font(20, bold=True),
        fill=COLORS["accent_soft"],
    )
    draw.text(
        (TERMINAL_MEDIA_BOX[2] - 468, TERMINAL_MEDIA_BOX[1] + 15),
        "TOP 500 ROWS • SAFE-AREA FIT",
        font=font(18, bold=True),
        fill=COLORS["muted"],
    )
    draw_footer(image, "TERMINAL SOURCE RETAINED • NO SLIDE OVERLAP")
    image.save(output_path, format="PNG", optimize=True)


def render_live_camera_frame(scene: Scene, output_path: Path) -> None:
    metadata = json.loads(LIVE_CAMERA_METADATA.read_text(encoding="utf-8"))
    image = base_canvas()
    draw = ImageDraw.Draw(image)
    draw_header(image, scene, compact=True)

    camera_box = LIVE_CAMERA_CONTENT_BOXES[scene.index]
    camera_card = (
        camera_box[0] - 14,
        camera_box[1] - 14,
        camera_box[2] + 14,
        camera_box[3] + 14,
    )
    draw.rounded_rectangle(
        camera_card,
        radius=24,
        fill="#020b16",
        outline=COLORS["accent"],
        width=3,
    )

    if scene.index == 6:
        details_box = (1250, 256, 1810, 903)
        draw.rounded_rectangle(
            details_box,
            radius=24,
            fill="#10263a",
            outline=COLORS["card_edge"],
            width=3,
        )
        draw.text(
            (1280, 292),
            "PHYSICAL UVC INPUT",
            font=font(25, bold=True),
            fill=COLORS["accent_soft"],
        )
        details = (
            "Orange Pi 5 Plus",
            f"{metadata['device']} · {metadata['driver']}",
            f"{metadata['width']}×{metadata['height']} {metadata['pixel_format']}",
            f"{metadata['frame_count']} frames · {metadata['duration_seconds']:.0f} s",
            f"UTC {metadata['started_at_utc']}",
            f"SHA-256  {metadata['video_sha256'][:12]}…",
        )
        for row, value in enumerate(details):
            draw.text((1280, 362 + row * 72), value, font=font(23), fill=COLORS["white"])
        draw_pill(image, (1280, 826), "NOT A REPOSITORY SAMPLE", COLORS["warning"])
    else:
        chart_box = card(image, (1150, 256, 1810, 846), padding=22)
        paste_contained(image, CHARTS / "09-so100-id1.png", chart_box)
        draw_pill(image, (130, 866), "PHYSICAL USB CAMERA", COLORS["accent"])
        draw_pill(image, (1164, 866), "SUPERVISED SO-100 CYCLE", COLORS["warning"])
        draw.text(
            (130, 925),
            "Camera and arm evidence are physical, but they are not synchronized on one sequence.",
            font=font(22),
            fill=COLORS["white"],
        )

    draw_footer(image, "PHYSICAL CAMERA SOURCE • PROVENANCE RECORDED")
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
    media_kind = scene_media_kind(scene.index)

    if media_kind == "terminal":
        left, top, right, bottom = TERMINAL_CONTENT_BOX
        media_width = right - left
        media_height = bottom - top
        command = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-i",
            str(frame_path),
            "-ss",
            f"{TERMINAL_STARTS[scene.index]:.3f}",
            "-i",
            str(TERMINAL_VIDEO),
            "-i",
            str(audio_path),
            "-filter_complex",
            (
                f"[0:v]scale={WIDTH}:{HEIGHT}[base];"
                f"[1:v]crop=iw:500:0:0,scale={media_width}:{media_height}:"
                "force_original_aspect_ratio=decrease:force_divisible_by=2,"
                f"pad={media_width}:{media_height}:(ow-iw)/2:(oh-ih)/2:color=0x020b16[media];"
                f"[base][media]overlay={left}:{top}:shortest=0,"
                f"fade=t=in:st=0:d=0.35,fade=t=out:st={fade_out}:d=0.4,"
                "format=yuv420p[v];"
                f"[2:a]{audio_filter}"
            ),
        ]
    elif media_kind == "live-camera":
        left, top, right, bottom = LIVE_CAMERA_CONTENT_BOXES[scene.index]
        media_width = right - left
        media_height = bottom - top
        command = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-i",
            str(frame_path),
            "-stream_loop",
            "-1",
            "-ss",
            f"{LIVE_CAMERA_STARTS[scene.index]:.3f}",
            "-i",
            str(LIVE_CAMERA_VIDEO),
            "-i",
            str(audio_path),
            "-filter_complex",
            (
                f"[0:v]scale={WIDTH}:{HEIGHT}[base];"
                f"[1:v]scale={media_width}:{media_height}:"
                "force_original_aspect_ratio=decrease:force_divisible_by=2,"
                f"pad={media_width}:{media_height}:(ow-iw)/2:(oh-ih)/2:color=0x020b16[media];"
                f"[base][media]overlay={left}:{top}:shortest=0,"
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
    camera_metadata = json.loads(LIVE_CAMERA_METADATA.read_text(encoding="utf-8"))
    manifest: dict[str, object] = {
        "schema_version": 1,
        "generator": relative(Path(__file__)),
        "voice": {"provider": "Microsoft Edge TTS", "name": VOICE, "rate": VOICE_RATE},
        "terminal_source": {
            "path": relative(TERMINAL_VIDEO),
            "sha256": sha256(TERMINAL_VIDEO),
            "disclosure": "Archived terminal evidence, cropped and fitted inside the projection safe area.",
        },
        "live_camera_source": {
            "path": relative(LIVE_CAMERA_VIDEO),
            "sha256": sha256(LIVE_CAMERA_VIDEO),
            "metadata_path": relative(LIVE_CAMERA_METADATA),
            "metadata_sha256": sha256(LIVE_CAMERA_METADATA),
            "source_kind": camera_metadata["source_kind"],
            "captured_at_utc": camera_metadata["started_at_utc"],
            "hostname": camera_metadata["hostname"],
            "device": camera_metadata["device"],
            "driver": camera_metadata["driver"],
            "frame_count": camera_metadata["frame_count"],
            "disclosure": camera_metadata["claim_boundary"],
        },
        "scenes": [
            {
                "index": scene.index,
                "duration_seconds": scene.duration,
                "title": scene.title,
                "narration_sha256": hashlib.sha256(scene.narration.encode("utf-8")).hexdigest(),
                "raw_audio_seconds": round(audio_durations[scene.index], 3),
                "media_kind": scene_media_kind(scene.index),
                "terminal_source_start_seconds": TERMINAL_STARTS.get(scene.index),
                "live_camera_source_start_seconds": LIVE_CAMERA_STARTS.get(scene.index),
            }
            for scene in scenes
        ],
        "outputs": {
            "video": {"path": relative(video), "sha256": sha256(video), "duration_seconds": 300.0},
            "subtitles": {"path": relative(subtitles), "sha256": sha256(subtitles)},
        },
        "limitations": [
            "The displayed camera footage is a physical USB capture, but it is not synchronized with RKNN, RTOS, or SO-100 events.",
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
