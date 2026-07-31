"""
Generate self-contained agent prompts from section_index.json.
Each prompt includes OCR data + domain knowledge for one section.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTION_INDEX = ROOT / "output" / "section_index.json"
PROMPTS_DIR = ROOT / "output" / "prompts"
OCR_DIR = ROOT / "output" / "ocr"

DOMAIN_KNOWLEDGE = """## 关键领域知识

**打桩船 + 船用锤配对规律：**
- 50m架高打桩船：用于一级、二级土壤，三级为 —
- 60m架高打桩船：一级、二级为 —，三级土壤才用
- 船用锤272kN.m：配对50m船，仅一级、二级有值，三级为 —
- 船用锤334kN.m：配对60m船，仅三级有值，一级、二级为 —

**涂料项目规律：**
- 沥青、红丹、汽油、煤油：按桩长分组，同桩长内各级土壤值相同

**拼组钢板桩消耗量规律：**
- 钢板桩/桩木/圆木在第2行以(parenthetical)形式出现，如 (10.15)
- 密度规律：同桩长内 (10.15)/(10.20)/(10.25) 按土级循环
- 一级→(10.15)，二级→(10.20)，三级→(10.25)

**统一值项目（所有定额编号同一值）：**
- 60t旋转扒杆起重船、15t平板拖车组、8t汽车式起重机、板枋材

**分组值项目：**
- 294kW拖轮：按桩长分组，同桩长内各级土壤值相同
- 400t方驳：按桩长分组，同桩长内值随土级递增
- 15t/40t履带式起重机：按桩长分组，值随土级递增

**OCR常见错误修正：**
- "围抢" → "围堰", "围捻" → "围堰"
- "般土方" → "一般土方", "冻士" → "冻土"
- "瘦班" → "艘班", "32400t方驳" → "400t方驳"
- "33294kW拖轮" → "294kW拖轮"
- 合并基价值需按代码列x位置拆分，如 "28215.1721477.22" → "28215.17" + "21477.22"

**临时拼组 vs 常规拼组：**
- 临时拼组材料15项（无桩木、圆木）
- 常规拼组材料17项（含桩木、圆木）
- 临时围堰材料13项（无铁件、钢材、电焊条，含钢丝绳、卡环）

**其他章节通用知识：**
- 定额编号为4位数字（1001-6999）
- 基价始终是每个定额编组的最后一行
- 数量为 —（全角破折号）表示该组合不适用
- 水上运距附加费：仅当页面上出现"附注：水上运距超过1km"时才添加单独的运距表
- 费用项目列包含：人工、材料、机械/船机、基价 等
"""

SYSTEM_PROMPT = """You are a specialized agent that converts OCR data from a Chinese construction norms book into structured Markdown tables.

The OCR data comes from 《沿海港口水工建筑工程定额》, a scanned PDF with OCR text blocks containing coordinates (x1,y1,x2,y2), text, and confidence scores.

Your task:
1. Read the OCR blocks carefully, understanding the page layout from coordinates
2. Identify: chapter/section titles → subsection headers → work content → table headers → data rows
3. Expand multi-dimensional headers into flat rows
4. Correct OCR errors using domain knowledge
5. Output ONE Markdown file per page to output/md/page_XXXX.md

CRITICAL RULES:
- Every norms_code × cost_item combination = one row in the table
- Norms codes (4-digit numbers like 1001, 2285) appear in EACH data row (do NOT merge cells)
- 基价 (base price) is always the LAST row for each norms code group
- Use — (full-width em dash) for empty/inapplicable values, NEVER leave cells empty
- All numbers must be accurate - verify against OCR data, do not hallucinate values
- If the page has a transport surcharge note ("水上运距每增1km"), add a separate table below the main one
- For continued pages, prepend "（接前页）" after the heading

OUTPUT FORMAT (strict):
```markdown
---
page: {page_number}
type: norms_table
chapter: {chapter}
section: {section}
continued_from: {prev_page_or_null}
---

# 第{page_number}页

## {heading}

（接前页）

- **工程内容**: {description}
- **单位**: {unit}

| 定额编号 | 分部工程 | 分项工程 | {attr_columns} | 费用项目 | 单位 | 数量 |
|:---|:---|:---|:---|:---|:---:|---:|
| {code} | {part} | {sub} | {attrs} | {item} | {unit} | {amount} |
```

After writing ALL page files, output a brief summary of what was done."""


def load_section_index():
    with open(SECTION_INDEX, "r", encoding="utf-8") as f:
        return json.load(f)


def load_ocr(page_num):
    path = OCR_DIR / f"ocr_{page_num:04d}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_prompt(section):
    """Generate a self-contained agent prompt for one section."""
    pages = section["pages"]
    section_id = section["section_id"]

    # Load OCR data for all pages
    ocr_data = {}
    total_blocks = 0
    for p in pages:
        data = load_ocr(p)
        if data:
            ocr_data[p] = data
            total_blocks += len(data)

    if not ocr_data:
        return None

    # Build context
    lines = []
    lines.append(f"## 任务：将以下定额表OCR数据转换为Markdown")
    lines.append("")
    lines.append("### 页面上下文")
    lines.append(f"- 章节：{section.get('chapter', '未知')}")
    lines.append(f"- 节：{section.get('section', '未知')}")

    subsection = section.get("subsection", "")
    if subsection:
        lines.append(f"- 分项：{subsection}")

    lines.append(f"- 页码范围：{pages}（共 {len(pages)} 页）")

    code_range = section.get("code_range")
    if code_range:
        lines.append(f"- 定额编号范围：{code_range[0]} - {code_range[1]}")

    lines.append(f"- 代码列数：{section.get('num_columns', 0)}")

    lengths = section.get("lengths", [])
    if lengths:
        lines.append(f"- 桩长/属性列表：{lengths}")

    unit = section.get("unit", "")
    if unit:
        lines.append(f"- 单位：{unit}")

    if section.get("has_transport_surcharge"):
        lines.append("- 包含水上运距附加费表")

    continued = section.get("continued_from")
    if continued:
        lines.append(f"- 续前页：第{continued}页")

    eng_content = section.get("engineering_content", "")
    if eng_content:
        lines.append(f"- 工程内容：{eng_content}")

    lines.append("")
    lines.append(DOMAIN_KNOWLEDGE)
    lines.append("")

    # Add OCR data (compact format to save context)
    lines.append("### OCR数据")
    lines.append("")

    for p in sorted(pages):
        data = ocr_data.get(p, [])
        if not data:
            lines.append(f"#### 页 {p}: NO OCR DATA")
            continue

        # Compact representation: only include essential fields
        lines.append(f"#### 页 {p} ({len(data)} blocks)")
        lines.append("```json")
        # Truncate if too large (>800 blocks per page, keep essential info)
        compact = []
        for b in data:
            compact.append({
                "x": round((b["x1"] + b["x2"]) / 2, 1),
                "y": round((b["y1"] + b["y2"]) / 2, 1),
                "t": b["text"],
                "c": round(b.get("confidence", 0), 2),
            })
        # Sort by y then x
        compact.sort(key=lambda b: (b["y"], b["x"]))
        lines.append(json.dumps(compact, ensure_ascii=False))
        lines.append("```")
        lines.append("")

    lines.append("### 输出要求")
    lines.append("")
    lines.append(f"为每页输出 Markdown 到 `output/md/page_XXXX.md`，格式严格遵循上述 OUTPUT FORMAT。")
    lines.append(f"共需输出 {len(pages)} 个文件。")
    lines.append("")
    lines.append("### 处理步骤")
    lines.append("")
    lines.append("1. 按 y 坐标排序所有 OCR blocks，理解页面垂直结构")
    lines.append("2. 识别章节标题、分项标题、工程内容区域")
    lines.append("3. 识别代码列的 x 范围（多个4位数字的x中心位置）")
    lines.append("4. 识别属性分组头（桩长、土壤级别等标签）")
    lines.append("5. 逐行解析费用项目名称和对应的数据值")
    lines.append("6. 将每个数据值映射到正确的定额编号")
    lines.append("7. 应用领域知识修正 OCR 错误")
    lines.append("8. 输出 Markdown 表格")
    lines.append("")

    prompt = "\n".join(lines)
    return prompt, total_blocks


def main():
    data = load_section_index()
    sections = data.get("sections", [])

    # Only process norms sections
    norms_sections = [s for s in sections if not s.get("is_text_page") and s.get("section_id")]

    if not norms_sections:
        print("No norms sections found")
        return

    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

    total_prompts = 0
    total_blocks = 0
    skipped_large = []

    for sec in norms_sections:
        sid = sec["section_id"]
        result = generate_prompt(sec)
        if result is None:
            continue
        prompt, blocks = result

        # Skip sections with too many blocks (>12000 = risk context overflow)
        if blocks > 12000:
            skipped_large.append((sid, blocks, sec["page_count"]))
            continue

        out_path = PROMPTS_DIR / f"section_{sid}.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(prompt)

        total_prompts += 1
        total_blocks += blocks

    print(f"生成 {total_prompts} 个 prompt 文件到 {PROMPTS_DIR}")
    print(f"总计 {total_blocks} 个 OCR blocks")

    if skipped_large:
        print(f"\n跳过大节（>12000 blocks）: {len(skipped_large)}")
        for sid, blocks, pages in skipped_large:
            print(f"  {sid}: {blocks} blocks, {pages} pages")

    print(f"\n输出目录: {PROMPTS_DIR}")


if __name__ == "__main__":
    main()
