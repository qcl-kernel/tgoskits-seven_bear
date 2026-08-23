#!/usr/bin/env python3
"""Polish structured Chinese copy with agy and retain an auditable manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODEL = "gemini-3.7-flash-high"
AGY_WSL_PATH = "/home/seven_wsl/.local/bin/agy"
PROTECTED_PATTERN = re.compile(
    r"```[\s\S]*?```|(?<!`)`[^`\r\n]+`(?!`)|"
    r"\{[a-zA-Z_][a-zA-Z0-9_]*\}|https?://\S+|"
    r"\b[0-9a-f]{7,64}\b|(?<![A-Za-z])[+-]?\d+(?:[,.]\d+)*(?:\.\d+)?(?:%|/\d+)?"
)
CHINESE_COUNT_WORDS = {
    "0": "零",
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
    "10": "十",
}
CHINESE_COUNT_CLASSIFIERS = "个项次组条类份张路轮层种块台对"


def main() -> int:
    args = parse_args()
    root = find_repo_root(Path(args.repo_root).resolve())
    source_path = root / args.source
    output_path = root / args.output
    manifest_path = root / args.manifest
    source = load_string_map(source_path)

    polished: dict[str, str] = {}
    calls: list[dict[str, Any]] = []
    items = list(source.items())
    for start in range(0, len(items), args.batch_size):
        batch = dict(items[start : start + args.batch_size])
        result, metadata = polish_batch_with_retries(batch, args.purpose, args.retries)
        validate_batch(batch, result)
        polished.update(result)
        calls.append(metadata)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_bytes = encoded_json(polished)
    output_path.write_bytes(output_bytes)
    update_manifest(
        manifest_path,
        {
            "source": source_path.relative_to(root).as_posix(),
            "output": output_path.relative_to(root).as_posix(),
            "purpose": args.purpose,
            "model": MODEL,
            "effort": "high",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "output_sha256": hashlib.sha256(output_bytes).hexdigest(),
            "entry_count": len(polished),
            "calls": calls,
        },
    )
    print(
        "AGY_POLISH_PASS "
        f"model={MODEL} entries={len(polished)} output={output_path.relative_to(root).as_posix()}"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--purpose", required=True)
    parser.add_argument(
        "--manifest",
        default="competition/submission/agy-polish-manifest.json",
    )
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "competition/requirement.md").is_file():
            return candidate
    raise RuntimeError(f"repository root not found from {start}")


def load_string_map(path: Path) -> dict[str, str]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()
    ):
        raise TypeError(f"expected a string-to-string object in {path}")
    if not parsed:
        raise ValueError(f"copy source is empty: {path}")
    return parsed


def polish_batch_with_retries(
    source: dict[str, str], purpose: str, retries: int
) -> tuple[dict[str, str], dict[str, Any]]:
    errors: list[str] = []
    for attempt in range(1, retries + 1):
        try:
            result, metadata = polish_batch(source, purpose)
            metadata["attempt"] = attempt
            return result, metadata
        except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
            errors.append(str(error))
            if attempt < retries:
                time.sleep(min(attempt * 2, 6))
    raise RuntimeError(f"agy failed after {retries} attempts: {' | '.join(errors)}")


def polish_batch(source: dict[str, str], purpose: str) -> tuple[dict[str, str], dict[str, Any]]:
    schema = {
        "type": "object",
        "properties": {key: {"type": "string"} for key in source},
        "required": list(source),
        "additionalProperties": False,
    }
    prompt = build_prompt(source, purpose)
    command = [
        "wsl.exe",
        "-e",
        AGY_WSL_PATH,
        "--new-project",
        "--model",
        MODEL,
        "--effort",
        "high",
        "--disable-slash-commands",
        "--output-format",
        "json",
        f"--json-schema={json.dumps(schema, ensure_ascii=False, separators=(',', ':'))}",
        f"--print={prompt}",
    ]
    process = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=360,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"agy failed with exit {process.returncode}: {process.stderr.strip()}\n{process.stdout.strip()}"
        )
    outer = json.loads(process.stdout)
    if outer.get("status") != "SUCCESS":
        raise RuntimeError(f"agy returned non-success status: {outer}")
    response = outer.get("response")
    parsed = find_structured_response(response, source)
    result = {key: str(parsed[key]) for key in source if key in parsed}
    metadata = {
        "conversation_id": outer.get("conversation_id"),
        "duration_seconds": outer.get("duration_seconds"),
        "usage": outer.get("usage"),
        "entry_ids": list(source),
        "input_sha256": hashlib.sha256(encoded_json(source)).hexdigest(),
        "output_sha256": hashlib.sha256(encoded_json(result)).hexdigest(),
    }
    return result, metadata


def find_structured_response(response: Any, source: dict[str, str]) -> dict[str, Any]:
    if isinstance(response, dict):
        candidates = [response]
    elif isinstance(response, str):
        candidates = decode_concatenated_objects(response)
    else:
        raise TypeError("agy structured response has an unsupported type")
    for candidate in candidates:
        if isinstance(candidate, dict) and set(source).issubset(candidate):
            return candidate
    raise TypeError(f"agy structured response does not contain all requested keys: {candidates}")


def decode_concatenated_objects(response: str) -> list[Any]:
    decoder = json.JSONDecoder()
    values: list[Any] = []
    offset = 0
    while offset < len(response):
        while offset < len(response) and response[offset].isspace():
            offset += 1
        if offset >= len(response):
            break
        value, offset = decoder.raw_decode(response, offset)
        values.append(value)
    return values


def build_prompt(source: dict[str, str], purpose: str) -> str:
    payload = json.dumps(source, ensure_ascii=False, indent=2)
    return f"""你是严谨的中文技术编辑。请润色以下用于{purpose}的文字，并按给定 JSON Schema 只返回 JSON 对象。直接在回复中完成，不要调用任何工具、技能或读取文件。

硬性约束：
1. 保留所有键，不增删、不改名、不调换键与文字的对应关系。
2. 不新增功能、成绩、测试、因果关系或结论；不得把历史证据改写成当前 HEAD 重跑。
3. 原样保留所有数字、正负号、百分比、单位、路径、URL、提交哈希、反引号内容、Markdown 结构和 `{{placeholder}}`。
4. 保留 PASS、BLOCKED、PILOT 等证据等级，不把 observed maximum 写成 WCET，不把 SO-100 单关节测试写成视觉物理闭环。
5. 中文应自然、简洁、适合比赛技术文档或画面；减少口号和空泛形容词。
6. 不输出解释、前言或代码围栏。

原始对象：
{payload}
"""


def validate_batch(source: dict[str, str], polished: dict[str, str]) -> None:
    if set(source) != set(polished):
        missing = sorted(set(source) - set(polished))
        extra = sorted(set(polished) - set(source))
        raise ValueError(f"agy key mismatch: missing={missing}, extra={extra}")
    for key, original in source.items():
        output = polished[key]
        if not output.strip():
            raise ValueError(f"agy returned empty text for {key}")
        original_tokens = Counter(PROTECTED_PATTERN.findall(original))
        output_tokens = Counter(PROTECTED_PATTERN.findall(output))
        missing = original_tokens - output_tokens
        extras = output_tokens - original_tokens
        disallowed_extras = {
            token: count
            for token, count in extras.items()
            if count > allowed_chinese_count_conversions(original, token)
        }
        if missing or disallowed_extras:
            raise ValueError(
                f"protected token drift in {key}: missing={dict(missing)}, "
                f"disallowed_extras={disallowed_extras}, "
                f"expected={dict(original_tokens)}, actual={dict(output_tokens)}"
            )


def allowed_chinese_count_conversions(source: str, token: str) -> int:
    chinese = CHINESE_COUNT_WORDS.get(token)
    if chinese is None:
        return 0
    return len(re.findall(rf"{chinese}(?=[{CHINESE_COUNT_CLASSIFIERS}])", source))


def update_manifest(path: Path, record: dict[str, Any]) -> None:
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
    else:
        manifest = {"schema_version": 1, "records": []}
    records = manifest.get("records")
    if not isinstance(records, list):
        raise TypeError(f"invalid manifest records in {path}")
    records = [item for item in records if item.get("output") != record["output"]]
    records.append(record)
    manifest["records"] = sorted(records, key=lambda item: item["output"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded_json(manifest))


def encoded_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
