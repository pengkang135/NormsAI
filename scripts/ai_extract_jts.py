#!/usr/bin/env python3
"""AI semantic extraction from clustered JSON.
Sends column-aligned data to Claude API for per-page semantic understanding
of multi-dimensional table headers, cost items, and continued tables.

Usage:
  python scripts/ai_extract_jts.py 97              # single page
  python scripts/ai_extract_jts.py 94-100          # page range
  python scripts/ai_extract_jts.py --all            # all pages
  python scripts/ai_extract_jts.py --model claude-haiku-4-5-20251001  # faster model
"""

import json, sys, re, os, io, time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
CLUSTERED_DIR = ROOT / "output" / "intermediate" / "clustered"
OUT_DIR = ROOT / "output" / "intermediate" / "extracted"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ─── Prompt building ───

def build_prompt(clustered, prev_result=None):
    """Build AI prompt for one page."""

    if clustered.get("is_continued") and prev_result:
        return _build_continued_prompt(clustered, prev_result)
    return _build_full_prompt(clustered)


def _build_full_prompt(c):
    columns_desc = []
    for col in c["code_columns"]:
        htexts = [h["text"] for h in col["header_texts"]]
        columns_desc.append(f"  {col['code']}: {htexts}")

    cost_desc = []
    for ci in c["cost_items"]:
        cost_desc.append(f"  {ci['name']} | {ci['unit']} | {ci['code']}")

    rows_desc = []
    for dr in c["data_rows"]:
        vals = ", ".join(f"{k}={v}" for k, v in dr["values"].items())
        rows_desc.append(f"  {dr['name']} | {dr['unit']} | {vals}")

    return f"""你是一个工程造价定额数据的结构化提取器。

给你一页定额表的结构化数据。每列的 header_texts 是从上到下的表头文本序列，
data_rows 是费用项目行及各列数值（null="－"）。

请分析并输出这页的完整 1D 结构化数据。只输出 JSON，不要解释。

## 页面信息

- 分项标题: {c.get('subsection', '')}
- 工程内容: {c.get('work_content', '')}
- 单位: {c.get('unit', '')}
- 是否续表: {c.get('is_continued', False)}

## 列定义（定额编号 + 表头文本序列）

{chr(10).join(columns_desc)}

## 费用项目

{chr(10).join(cost_desc)}

## 数据行（每行名称 + 各列数值）

{chr(10).join(rows_desc)}

## 你需要做的事

1. 分析每列 header_texts 文本序列，推断属性维度 (attr_dimensions)
   - 同一 y 层级的文本属于同一属性维度
   - 跨列相同的文本通常是属性名标签（如"土壤类别"）
   - 列间取值不同的文本是属性值（如"地槽"、"地坑"）
   - 融合标签（如"斗容2.0m³"）拆分：属性名="斗容", 值="2.0m³"
   - 纯数字文本（如"75"、"105"）是属性值，需与上方的名称文本关联
   - 括号内的单位（如"（kW）"）是属性名的补充，应与名称合并

2. 处理同名费用项目
   - 如"其他材料"出现两次且单位不同→改为"其他材料(元)"和"其他材料(%)"
   - 单位不同=不同cost item

3. 构建 attr_dimensions 数组
   - 每个元素: {{"name": "<属性名>", "values": ["<列1值>", "<列2值>", ...]}}
   - values 顺序与 code_columns 顺序一致
   - 值可能为空字符串

4. 展开 items：每个定额编号 x 每行费用项目 = 一条记录
   - null 表示该组合不适用（表格中的"—"或"－"）

## 输出格式

{{
  "attr_dimensions": [
    {{"name": "<属性名>", "values": ["<列1值>", "<列2值>", ...]}}
  ],
  "cost_items": [
    {{"name": "<费用项目名>", "unit": "<单位>", "code": "<代码>"}}
  ],
  "items": [
    {{
      "norms_code": "<定额编号>",
      "cost_item": "<费用项目名>",
      "cost_item_unit": "<单位>",
      "code": "<代码>",
      "amount": <数值或null>,
      "attr_<属性名>": "<值>"
    }}
  ]
}}

## 关键规则

1. 属性不遗漏：header_texts 中每个有意义的层级都要提取
2. 属性名用有意义的描述（中文），不要用"属性1"、"属性2"
3. items 数量 = len(norms_codes) x len(cost_items)
4. null != 0：表格中的"—"输出 null
5. 只输出 JSON，不要任何解释文字
"""


def _build_continued_prompt(c, prev):
    prev_ctx = {
        "attr_dimensions": prev.get("attr_dimensions", []),
        "cost_items": prev.get("cost_items", []),
    }

    rows_desc = []
    for dr in c["data_rows"]:
        vals = ", ".join(f"{k}={v}" for k, v in dr["values"].items())
        rows_desc.append(f"  {dr['name']} | {dr['unit']} | {vals}")

    return f"""你是一个工程造价定额数据的结构化提取器。

这是一个**续前表**页面。前页的 attr_dimensions 和 cost_items 定义如下：

{json.dumps(prev_ctx, ensure_ascii=False, indent=2)}

本页只有数据行，表头结构继承自前页。

## 本页数据行

{chr(10).join(rows_desc)}

请提取本页的 items，沿用前页的 attr_dimensions 和 cost_items。
只输出 JSON，不要解释。

## 输出格式

{{
  "items": [
    {{
      "norms_code": "<定额编号>",
      "cost_item": "<费用项目名>",
      "cost_item_unit": "<单位>",
      "code": "<代码>",
      "amount": <数值或null>,
      "attr_<属性名>": "<值>"
    }}
  ]
}}
"""


# ─── AI call ───

def call_ai(prompt, model="claude-haiku-4-5-20251001"):
    """Call Claude API. Falls back to sonnet on failure."""
    import anthropic
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def extract_json(response_text):
    """Extract JSON from AI response (may be wrapped in ```json blocks)."""
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response_text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    # Try bare JSON
    return json.loads(response_text)


def extract_page(pg, prev_result=None, model="claude-haiku-4-5-20251001"):
    """Extract one page via AI, with retry.

    For continued tables, prev_result provides attr_dimensions and cost_items.
    """
    fpath = CLUSTERED_DIR / f"page_{pg:04d}.json"
    if not fpath.exists():
        return None, "no clustered file"

    with open(fpath, 'r', encoding='utf-8') as f:
        clustered = json.load(f)

    if not clustered.get("code_columns"):
        return None, "no code columns"

    prompt = build_prompt(clustered, prev_result)
    is_continued = clustered.get("is_continued", False)
    n_codes = len(clustered["code_columns"])
    n_ci = len(clustered.get("cost_items", []))
    expected = n_codes * n_ci

    for attempt in range(3):
        try:
            response_text = call_ai(prompt, model=model)
            result = extract_json(response_text)

            # Validate item count
            actual = len(result.get("items", []))
            if actual != expected and not is_continued:
                if attempt < 2:
                    prompt = (
                        f"你上次的输出 items 数量不对（期望 {expected}={n_codes}×{n_ci}，实际 {actual}）。"
                        f"请补全所有定额编号×费用项目的组合。\n\n{prompt}"
                    )
                    time.sleep(1)
                    continue

            return result, None

        except json.JSONDecodeError:
            if attempt < 2:
                prompt = "你上次的输出不是合法 JSON。请严格按格式输出。\n\n" + prompt
                time.sleep(1)
        except Exception as e:
            err_msg = str(e)
            if "overloaded" in err_msg.lower() or "429" in err_msg:
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue
            if attempt >= 2:
                return None, err_msg
            time.sleep(1)

    return None, "max retries exceeded"


# ─── Main ───

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", nargs="?", help="page number, range (e.g. 90-100), or --all")
    ap.add_argument("--all", action="store_true", help="process all clustered pages")
    ap.add_argument("--model", default="claude-haiku-4-5-20251001",
                    help="Claude model to use")
    ap.add_argument("--limit", type=int, default=0, help="max pages to process (0=all)")
    args = ap.parse_args()

    if args.all or not args.pages:
        pages = []
        for fpath in sorted(CLUSTERED_DIR.glob("page_*.json")):
            m = re.match(r'page_(\d+)\.json', fpath.name)
            if m:
                pages.append(int(m.group(1)))
    elif '-' in (args.pages or ""):
        start, end = args.pages.split('-')
        pages = list(range(int(start), int(end) + 1))
    else:
        pages = [int(args.pages)]

    if args.limit > 0:
        pages = pages[:args.limit]

    print(f"Model: {args.model}")
    print(f"Pages to process: {len(pages)}")
    print()

    prev = None
    ok_count = 0
    skip_count = 0
    fail_count = 0
    total_items = 0

    for i, pg in enumerate(sorted(pages)):
        result, error = extract_page(pg, prev, model=args.model)

        if error:
            if error == "no clustered file" or error == "no code columns":
                skip_count += 1
                prev = None
            else:
                fail_count += 1
                print(f"  P.{pg}: FAILED - {error}")
                prev = None
            continue

        # Merge in metadata from clustered
        fpath = CLUSTERED_DIR / f"page_{pg:04d}.json"
        with open(fpath, 'r', encoding='utf-8') as f:
            clustered = json.load(f)

        result["page"] = pg
        result["subsection"] = clustered.get("subsection", "")
        result["work_content"] = clustered.get("work_content", "")
        result["unit"] = clustered.get("unit", "")
        result["norms_codes"] = [c["code"] for c in clustered["code_columns"]]

        # Save
        out_path = OUT_DIR / f"page_{pg:04d}.json"
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        ni = len(result.get("items", []))
        na = len(result.get("attr_dimensions", []))
        total_items += ni
        ok_count += 1

        # Continue chain for continued tables
        if not clustered.get("is_continued"):
            prev = result
        else:
            pass  # prev stays (continued chain)

        if (i + 1) % 10 == 0:
            print(f"  ... {i+1}/{len(pages)}: {ok_count} ok, {fail_count} fail")

        print(f"  P.{pg}: {ni} items, {na} attrs")

    print(f"\nSummary: {ok_count} ok, {skip_count} skipped, {fail_count} failed")
    print(f"Total items: {total_items}")
    print(f"Output: {OUT_DIR}")


if __name__ == '__main__':
    main()
