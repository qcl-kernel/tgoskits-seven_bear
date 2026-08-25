#!/usr/bin/env python3
"""Assemble polished copy into Markdown, Typst wrappers, and a video script."""

from __future__ import annotations

import json
import re
from pathlib import Path


SUBMISSION = Path(__file__).resolve().parents[1]
COPY = SUBMISSION / "copy"
TYPST = SUBMISSION / "typst"
GENERATED = TYPST / "generated"


def main() -> int:
    routed = load_routed_corrections("evidence-count-corrections.json")
    version_refresh = load_routed_corrections("version-refresh.json")
    design = load_sections("design-sections.json")
    design.update(load_sections("design-corrections.json"))
    design.update(load_sections("design-final-corrections.json"))
    design.update(routed["design"])
    design.update(version_refresh["design"])
    design = {key: design[key] for key in sorted(design)}
    report = load_sections("test-sections.json")
    report.update(routed["test"])
    reproduction = load_sections("reproduction-sections.json")
    reproduction.update(routed["reproduction"])
    reproduction.update(version_refresh["reproduction"])
    video = load_sections("video-scenes.json")
    video.update(load_sections("video-final-corrections.json"))
    video.update(routed["video"])

    write_markdown(SUBMISSION / "design-document.md", design)
    write_markdown(SUBMISSION / "test-report.md", report)
    write_markdown(SUBMISSION / "reproduction-guide.md", reproduction)
    write_video_script(SUBMISSION / "video-script.md", video)

    GENERATED.mkdir(parents=True, exist_ok=True)
    write_pdf_body(GENERATED / "design-body.md", design)
    write_pdf_body(GENERATED / "test-body.md", report)
    write_typst_wrapper(
        TYPST / "design-document.typ",
        title=extract_title(design["00_cover"]),
        abstract=extract_abstract(design["00_cover"]),
        body="generated/design-body.typ",
    )
    write_typst_wrapper(
        TYPST / "test-report.typ",
        title=extract_title(report["00_cover"]),
        abstract=extract_abstract(report["00_cover"]),
        body="generated/test-body.typ",
    )
    print("DOCUMENT_ASSEMBLY_PASS documents=4 typst_wrappers=2")
    return 0


def load_sections(name: str) -> dict[str, str]:
    path = COPY / name
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError(f"invalid polished copy: {path}")
    if "\u2011" in "".join(data.values()):
        raise ValueError(f"nonbreaking hyphen is not allowed in {path}")
    return {key: data[key] for key in sorted(data)}


def load_routed_corrections(name: str) -> dict[str, dict[str, str]]:
    routed = {scope: {} for scope in ("design", "test", "reproduction", "video")}
    for routed_key, value in load_sections(name).items():
        scope, separator, key = routed_key.partition("__")
        if not separator or scope not in routed or not key:
            raise ValueError(f"invalid routed correction key: {routed_key}")
        routed[scope][key] = value
    return routed


def write_markdown(path: Path, sections: dict[str, str]) -> None:
    content = "\n\n".join(sections.values()).rstrip() + "\n"
    path.write_text(content, encoding="utf-8", newline="\n")


def write_pdf_body(path: Path, sections: dict[str, str]) -> None:
    body = "\n\n".join(value for key, value in sections.items() if key != "00_cover")
    body = body.replace("(assets/charts/", "(../../assets/charts/")
    path.write_text(body.rstrip() + "\n", encoding="utf-8", newline="\n")


def extract_title(cover: str) -> str:
    match = re.search(r"^# (.+)$", cover, flags=re.MULTILINE)
    if not match:
        raise ValueError("cover has no level-one title")
    return match.group(1).strip()


def extract_abstract(cover: str) -> str:
    paragraphs = [part.strip() for part in cover.split("\n\n")]
    for paragraph in paragraphs:
        if paragraph and not paragraph.startswith("#"):
            return paragraph
    raise ValueError("cover has no abstract paragraph")


def typst_escape(value: str) -> str:
    replacements = {
        "\\": "\\\\",
        "#": "\\#",
        "[": "\\[",
        "]": "\\]",
        "$": "\\$",
    }
    return "".join(replacements.get(character, character) for character in value)


def write_typst_wrapper(path: Path, *, title: str, abstract: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    title_markup = typst_escape(title)
    if len(title) > 20:
        title_markup = f"#text(size: 0.82em)[{title_markup}]"
    content = f'''#import "../vendor/ilm-zh/lib.typ": *

#show: ilm.with(
  title: [{title_markup}],
  author: "TGOSKits RT-IVC",
  fonts: (
    "宋体": ((name: "Times New Roman", covers: "latin-in-cjk"), "Noto Serif SC"),
    "黑体": ((name: "Arial", covers: "latin-in-cjk"), "Noto Sans SC"),
    "等宽": ((name: "Cascadia Mono", covers: "latin-in-cjk"), "Noto Sans SC"),
  ),
  date: datetime(year: 2026, month: 8, day: 25),
  date-format: "[year]-[month padding:zero]-[day padding:zero]",
  abstract: [{typst_escape(abstract)}],
  chapter-pagebreak: true,
  external-link-circle: false,
)

#set heading(numbering: none)
#show figure.where(kind: table): set text(size: 8pt)
#show figure.where(kind: image): set block(breakable: false)
#include "{body}"
'''
    path.write_text(content, encoding="utf-8", newline="\n")


def write_video_script(path: Path, video: dict[str, str]) -> None:
    scene_ids = sorted({key.split("_", 1)[0] for key in video})
    blocks = ["# TGOSKits RT-IVC competition video script"]
    for scene_id in scene_ids:
        blocks.extend(
            [
                f"## Scene {int(scene_id) + 1}",
                f"Title: {video[f'{scene_id}_title']}",
                f"Caption: {video[f'{scene_id}_caption']}",
                f"Narration: {video[f'{scene_id}_narration']}",
            ]
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    raise SystemExit(main())
