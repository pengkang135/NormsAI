"""
预扫描所有剩余 OCR JSON 文件，识别章节边界，输出 section_index.json。
"""
import json
import re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
OCR_DIR = ROOT / "output" / "ocr"
MD_DIR = ROOT / "output" / "md"
OUTPUT = ROOT / "output" / "section_index.json"

CHAPTER_PAT = re.compile(r"第[一二三四五六七八九十\d]+章")
SECTION_PAT = re.compile(r"第[一二三四五六七八九十\d]+节")
SUBSECTION_PAT = re.compile(r"^[一二三四五六七八九十\d]+[、，,.]")
CONTINUED_PAT = re.compile(r"续[前该]?表")
TRANSPORT_PAT = re.compile(r"水上运距")
UNIT_PATS = [re.compile(r"每\d+[根组m³t]"), re.compile(r"每\d+0根"), re.compile(r"每\d+0组")]
CODE_PAT = re.compile(r"^\d{4}$")
LENGTH_PAT = re.compile(r"^\d+$")
WITHIN_PAT = re.compile(r"以内")

# OCR noise corrections for section titles
TITLE_CORRECTIONS = {
    "围抢": "围堰",
    "围捻": "围堰",
}


def get_remaining_pages():
    """Return sorted list of page numbers that have OCR but no MD."""
    ocr_files = {int(f.stem.split("_")[1]): f for f in OCR_DIR.glob("ocr_*.json")}
    md_files = {int(f.stem.split("_")[1]) for f in MD_DIR.glob("page_*.md")}
    remaining = sorted(set(ocr_files.keys()) - md_files)
    return [(p, ocr_files[p]) for p in remaining]


def load_ocr(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def classify_page(blocks):
    """Classify a page based on its OCR content."""
    texts = [b["text"] for b in blocks]
    full_text = "".join(texts)

    # Count code-like numbers
    codes = [t for t in texts if CODE_PAT.match(t) and 1000 <= int(t) <= 9999]

    # Detect markers
    has_continued = any(CONTINUED_PAT.search(t) for t in texts)
    has_chapter = any(CHAPTER_PAT.search(t) for t in texts)
    has_section = any(SECTION_PAT.search(t) for t in texts)
    has_subsections = any(SUBSECTION_PAT.match(t) for t in texts)
    has_transport = any(TRANSPORT_PAT.search(t) for t in texts)
    has_codes = len(codes) >= 3

    # Detect unit
    unit = ""
    for t in texts:
        for pat in UNIT_PATS:
            m = pat.search(t)
            if m:
                unit = m.group()
                break
        if unit:
            break

    # Classify
    if has_chapter or has_section:
        if has_codes:
            page_type = "norms_table"
        else:
            page_type = "chapter_text"
    elif has_continued or has_codes:
        page_type = "norms_table"
    elif len(blocks) < 30:
        page_type = "blank_or_short"
    else:
        page_type = "chapter_text"

    return {
        "type": page_type,
        "has_continued": has_continued,
        "has_transport": has_transport,
        "unit": unit,
        "code_count": len(codes),
        "codes": sorted(set(codes), key=lambda x: int(x)),
    }


def extract_section_title(blocks):
    """Extract section/chapter title from page top area."""
    # Look at blocks in top 200px
    top_blocks = [b for b in blocks if b["y1"] < 200]
    top_blocks.sort(key=lambda b: b["y1"])

    titles = []
    for b in top_blocks:
        text = b["text"]
        # Apply corrections
        for wrong, correct in TITLE_CORRECTIONS.items():
            text = text.replace(wrong, correct)

        if CHAPTER_PAT.search(text) or SECTION_PAT.search(text) or SUBSECTION_PAT.match(text):
            if b["confidence"] > 0.5 and len(text) > 3:
                titles.append((b["y1"], text))

    if titles:
        titles.sort()
        return titles[0][1]
    return ""


def extract_code_columns(blocks):
    """Extract norms code column info from header area."""
    codes = []
    for b in blocks:
        if CODE_PAT.match(b["text"]) and 1000 <= int(b["text"]) <= 9999:
            if b["y1"] < 250:  # Only header codes
                codes.append({
                    "code": int(b["text"]),
                    "x": (b["x1"] + b["x2"]) / 2,
                    "y": b["y1"],
                })

    if not codes:
        return None

    codes.sort(key=lambda c: c["x"])
    code_numbers = [c["code"] for c in codes]
    x_positions = [c["x"] for c in codes]

    return {
        "codes": code_numbers,
        "count": len(code_numbers),
        "x_positions": x_positions,
        "min_x": min(x_positions) if x_positions else 0,
        "max_x": max(x_positions) if x_positions else 0,
    }


def extract_lengths(blocks):
    """Extract pile length labels from header area."""
    lengths = []
    within_blocks = [b for b in blocks if WITHIN_PAT.search(b["text"]) and b["y1"] < 250]

    for b in within_blocks:
        text = b["text"].replace(" ", "")
        m = re.match(r"(\d+)", text)
        if m:
            lengths.append(int(m.group(1)))

    if lengths:
        lengths.sort()
        return [f"{l}以内" for l in lengths]
    return []


def extract_engineering_content(blocks):
    """Extract engineering content description."""
    for b in blocks:
        if "工程内容" in b["text"]:
            # Find the full content text - it's usually a long line
            content_blocks = [
                bl for bl in blocks
                if abs(bl["y1"] - b["y1"]) < 30 and bl["x1"] < 750
            ]
            content_blocks.sort(key=lambda bl: bl["x1"])
            full_text = "".join(bl["text"] for bl in content_blocks)
            return full_text
    return ""


def group_into_sections(page_info_list):
    """Group consecutive pages into sections."""
    sections = []
    current_section = None

    for info in page_info_list:
        page_type = info["classification"]["type"]
        codes = info["classification"]["codes"]
        is_new_section = bool(info["section_title"]) and not info["classification"]["has_continued"]

        # Skip non-norms pages (they're handled separately)
        if page_type in ("blank_or_short", "chapter_text"):
            # Finalize current section if any
            if current_section:
                sections.append(current_section)
                current_section = None
            # Add as standalone text page
            sections.append({
                "section_id": None,
                "chapter": info["section_title"] or info.get("chapter", ""),
                "section": "",
                "subsection": "",
                "pages": [info["page"]],
                "page_count": 1,
                "code_range": None,
                "num_columns": 0,
                "lengths": [],
                "unit": "",
                "has_transport_surcharge": False,
                "continued_from": None,
                "page_types": [page_type],
                "is_text_page": True,
            })
            continue

        if is_new_section and current_section:
            sections.append(current_section)
            current_section = None

        if current_section is None:
            # Start new section
            code_info = info.get("code_columns")
            current_section = {
                "section_id": None,  # Will be assigned later
                "chapter": info.get("chapter", ""),
                "section": info.get("section", ""),
                "subsection": info.get("subsection", ""),
                "pages": [],
                "page_count": 0,
                "code_range": None,
                "num_columns": code_info["count"] if code_info else 0,
                "lengths": info.get("lengths", []),
                "unit": info["classification"]["unit"],
                "has_transport_surcharge": False,
                "continued_from": None,
                "page_types": [],
                "is_text_page": False,
                "engineering_content": info.get("engineering_content", ""),
            }

            if info["classification"]["has_continued"]:
                current_section["continued_from"] = info["page"] - 1

        current_section["pages"].append(info["page"])
        current_section["page_count"] = len(current_section["pages"])
        current_section["page_types"].append(page_type)
        if info["classification"]["has_transport"]:
            current_section["has_transport_surcharge"] = True

        # Update code range
        if codes:
            if current_section["code_range"] is None:
                current_section["code_range"] = [int(codes[0]), int(codes[-1])]
            else:
                current_section["code_range"][1] = max(
                    current_section["code_range"][1], int(codes[-1])
                )

        # Inherit unit if not set
        if not current_section["unit"] and info["classification"]["unit"]:
            current_section["unit"] = info["classification"]["unit"]

        # Inherit lengths if not set
        if not current_section["lengths"] and info.get("lengths"):
            current_section["lengths"] = info["lengths"]

    # Don't forget the last section
    if current_section:
        sections.append(current_section)

    # Assign section IDs
    for i, sec in enumerate(sections):
        if not sec["is_text_page"]:
            sec["section_id"] = f"s{i+1:03d}"

    return sections


def main():
    remaining = get_remaining_pages()
    print(f"剩余待处理页面: {len(remaining)}")

    page_info_list = []
    chapter_ctx = {"chapter": "", "section": "", "subsection": ""}

    for page_num, ocr_path in remaining:
        blocks = load_ocr(ocr_path)
        classification = classify_page(blocks)

        # Track chapter/section context
        title = extract_section_title(blocks)
        if title:
            if CHAPTER_PAT.search(title):
                chapter_ctx["chapter"] = title
                chapter_ctx["section"] = ""
                chapter_ctx["subsection"] = ""
            elif SECTION_PAT.search(title):
                chapter_ctx["section"] = title
                chapter_ctx["subsection"] = ""
            elif SUBSECTION_PAT.match(title):
                chapter_ctx["subsection"] = title

        code_columns = extract_code_columns(blocks) if classification["type"] == "norms_table" else None
        lengths = extract_lengths(blocks) if classification["type"] == "norms_table" else []
        eng_content = extract_engineering_content(blocks)

        page_info_list.append({
            "page": page_num,
            "classification": classification,
            "section_title": title,
            "chapter": chapter_ctx["chapter"],
            "section": chapter_ctx["section"],
            "subsection": chapter_ctx["subsection"],
            "code_columns": code_columns,
            "lengths": lengths,
            "engineering_content": eng_content,
        })

    sections = group_into_sections(page_info_list)

    # Summary statistics
    norms_sections = [s for s in sections if not s.get("is_text_page")]
    text_pages = [s for s in sections if s.get("is_text_page")]

    total_norms_pages = sum(s["page_count"] for s in norms_sections)
    total_text_pages = sum(s["page_count"] for s in text_pages)

    print(f"\n节划分结果:")
    print(f"  定额表节: {len(norms_sections)} 节, 共 {total_norms_pages} 页")
    print(f"  文字/空白页: {len(text_pages)} 节, 共 {total_text_pages} 页")

    # Print section summary
    print(f"\n节概览:")
    for sec in norms_sections:
        code_str = f"codes {sec['code_range'][0]}-{sec['code_range'][1]}" if sec["code_range"] else "no codes"
        pages_str = f"pp.{sec['pages'][0]}-{sec['pages'][-1]}" if len(sec["pages"]) > 1 else f"p.{sec['pages'][0]}"
        print(f"  {sec['section_id']}: {pages_str} | {code_str} | {sec['num_columns']}cols | {sec['subsection']} | {sec['unit']}")

    # Save
    output_data = {
        "total_remaining": len(remaining),
        "norms_section_count": len(norms_sections),
        "text_page_count": len(text_pages),
        "total_norms_pages": total_norms_pages,
        "total_text_pages": total_text_pages,
        "sections": sections,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"\n已输出: {OUTPUT}")


if __name__ == "__main__":
    main()
