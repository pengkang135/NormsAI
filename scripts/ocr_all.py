"""Run OCR on all 512 pages, skipping cached pages."""
import sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import OCR_DIR, DEFAULT_PAGE_RANGE
from src.ocr_engine import ocr_page

def main():
    total = 0
    cached = 0
    new = 0
    start = time.time()

    for page in DEFAULT_PAGE_RANGE:
        total += 1
        cache_path = OCR_DIR / f"ocr_{page:04d}.json"
        if cache_path.exists():
            cached += 1
            continue

        blocks = ocr_page(page)
        new += 1
        elapsed = time.time() - start
        pace = elapsed / new if new > 0 else 0
        remaining = pace * (512 - cached - new) / 60

        print(f"[{new:3d}] page {page:3d}: {len(blocks):3d} blocks  "
              f"| {elapsed:.0f}s elapsed | ~{remaining:.0f}min remaining")

    print(f"\nDone: total={total} cached={cached} new={new}  "
          f"elapsed={time.time()-start:.0f}s")


if __name__ == "__main__":
    main()
