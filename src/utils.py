import json
import re
from pathlib import Path
from statistics import median
from typing import Iterable


def ensure_dirs(paths: Iterable[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def cluster_1d(values: list[float], tolerance: float) -> list[float]:
    if not values:
        return []
    ordered = sorted(values)
    groups = [[ordered[0]]]
    for value in ordered[1:]:
        if value - groups[-1][-1] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [sum(group) / len(group) for group in groups]


def bbox_iou(a: dict, b: dict) -> float:
    x1 = max(a["x1"], b["x1"])
    y1 = max(a["y1"], b["y1"])
    x2 = min(a["x2"], b["x2"])
    y2 = min(a["y2"], b["y2"])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a["x2"] - a["x1"]) * max(0.0, a["y2"] - a["y1"])
    area_b = max(0.0, b["x2"] - b["x1"]) * max(0.0, b["y2"] - b["y1"])
    return inter / (area_a + area_b - inter + 1e-6)


def normalize_text(text: str) -> str:
    text = text or ""
    text = text.replace("冻士", "冻土").replace("毎", "每")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("I", "Ⅰ").replace("II", "Ⅱ").replace("III", "Ⅲ")
    return text


def strip_chapter_prefix(text: str) -> str:
    normalized = normalize_text(text)
    return re.sub(r"^[一二三四五六七八九十百千零]+、", "", normalized).strip()


def is_number_text(text: str) -> bool:
    if not text:
        return False
    cleaned = text.replace(" ", "")
    if cleaned.count(",") == 1 and "." not in cleaned:
        head, tail = cleaned.split(",", 1)
        if head.isdigit() and tail.isdigit() and 1 <= len(tail) <= 3:
            cleaned = f"{head}.{tail}"
        else:
            cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", "")
    return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned))


def safe_float(text: str) -> float | None:
    if not is_number_text(text):
        return None
    cleaned = text.replace(" ", "")
    if cleaned.count(",") == 1 and "." not in cleaned:
        head, tail = cleaned.split(",", 1)
        if head.isdigit() and tail.isdigit() and 1 <= len(tail) <= 3:
            cleaned = f"{head}.{tail}"
        else:
            cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", "")
    return float(cleaned)


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def read_json(path: Path) -> object:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def median_or_default(values: list[float], default: float) -> float:
    return median(values) if values else default


def dedupe_keep_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output
