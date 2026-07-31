from dataclasses import asdict

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageEnhance
from rapidocr_onnxruntime import RapidOCR

from config import OCR_CONFIDENCE_THRESHOLD, OCR_DIR, OCR_MULTI_PASS, PDF_PATH
from src.models import OCRBlock
from src.utils import bbox_iou, normalize_text, read_json, write_json


def render_page(page_num: int, pdf_path=PDF_PATH, scale: float = 2.0) -> Image.Image:
    pdf = pdfium.PdfDocument(str(pdf_path))
    page = pdf[page_num - 1]
    return page.render(scale=scale).to_pil()


def _run_pass(page_img: Image.Image, scale: float, contrast: float, label: str, engine: RapidOCR) -> list[OCRBlock]:
    width, height = page_img.size
    resized = page_img.resize((int(width * scale / 2.0), int(height * scale / 2.0)), Image.LANCZOS)
    if contrast != 1.0:
        resized = ImageEnhance.Contrast(resized).enhance(contrast)

    result, _ = engine(np.array(resized))
    if not result:
        return []

    blocks: list[OCRBlock] = []
    shrink = 2.0 / scale
    for box, text, conf in result:
        score = float(conf)
        if score < OCR_CONFIDENCE_THRESHOLD:
            continue
        cleaned = normalize_text(text)
        if not cleaned:
            continue
        blocks.append(
            OCRBlock(
                x1=float(box[0][0]) * shrink,
                y1=float(box[0][1]) * shrink,
                x2=float(box[2][0]) * shrink,
                y2=float(box[2][1]) * shrink,
                text=cleaned,
                confidence=score,
                pass_label=label,
            )
        )
    return blocks


def _dedupe_blocks(blocks: list[OCRBlock]) -> list[OCRBlock]:
    kept: list[OCRBlock] = []
    for block in sorted(blocks, key=lambda item: (-item.confidence, -len(item.text))):
        duplicate = None
        for existing in kept:
            if bbox_iou(asdict(block), asdict(existing)) > 0.5:
                duplicate = existing
                break
        if duplicate is None:
            kept.append(block)
            continue
        if len(block.text) > len(duplicate.text) or block.confidence > duplicate.confidence:
            duplicate.text = block.text
            duplicate.confidence = block.confidence
            duplicate.pass_label = block.pass_label
    kept.sort(key=lambda item: (item.y1, item.x1))
    return kept


def ocr_page(page_num: int, force: bool = False, pdf_path=PDF_PATH) -> list[OCRBlock]:
    cache_path = OCR_DIR / f"ocr_{page_num:04d}.json"
    if cache_path.exists() and not force:
        payload = read_json(cache_path)
        return [OCRBlock(**item) for item in payload]

    engine = RapidOCR()
    page_img = render_page(page_num, pdf_path=pdf_path, scale=2.0)
    passes: list[OCRBlock] = []
    for entry in OCR_MULTI_PASS:
        passes.extend(_run_pass(page_img, entry["scale"], entry["contrast"], entry["label"], engine))
    merged = _dedupe_blocks(passes)
    write_json(cache_path, [item.to_dict() for item in merged])
    return merged
