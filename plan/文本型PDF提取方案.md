# 定额PDF AI逐页提取方案

## 问题定义

当前脚本方案（坐标聚类 + 正则 + 规则）的核心缺陷：**无法可靠地理解多维表头结构**。

质量抽检结果（722页自动提取）：

| 指标 | 数值 |
|------|------|
| 页面零属性维度 | 195/722 (27%) |
| 第三章 avg_attr | 0.5（87/161页零属性，54%） |
| 人工配置 vs 自动 | avg_attr 2.5 → 0.7（下降72%） |
| cost_item误识别 | 15+页将数字/规格当作费用项目名 |
| items≠codes×cost | 136页 (19%) 存在同名合并错误 |

**根因**：`infer_attr_dimensions()` 试图用"中文=属性名/数字=属性值"的启发式规则推断属性语义，但这在处理多级表头（跨列标题、隐式属性、融合标签）时必然失败。

**结论：坐标聚类可以完成列对齐，但属性语义理解必须由AI完成。**

## 方案概述

```
PyMuPDF提取文本+坐标 → 坐标聚类(列对齐) → AI理解表头语义 → 输出1D JSON → SQLite → Browser
                         └── 确定性算法 ──┘   └── LLM ──┘
```

**核心思路**：将"坐标→列→属性"的确定性部分用算法完成，将"文本→属性语义"的不确定部分交给AI。

分两步：
1. **坐标聚类（本地算法）**：按y坐标分组为行，按x坐标对齐到列，识别定额编号列和数据行
2. **AI语义理解（LLM）**：输入每列的表头文本序列 + 页面元数据，输出属性维度定义和费用项目列表

## 数据流

```
Step 1: PyMuPDF全量文本提取 (已完成)
  scripts/extract_text_all.py
  → output/intermediate/text/page_0001.json ~ page_0914.json

Step 2: 坐标聚类 + 列对齐 (新脚本)
  scripts/cluster_columns.py
  → output/intermediate/clustered/page_XXXX.json
  (每页输出：按列组织的文本块 + 数据行的列值映射)

Step 3: AI逐页语义理解 (新脚本)
  scripts/ai_extract_page.py
  → output/intermediate/extracted/page_XXXX.json
  (每页调用LLM API，输出1D结构化数据)

Step 4: 入库 (现有脚本，需适配)
  scripts/load_extracted_to_sqlite.py
  → output/db/jts_norms.sqlite

Step 5: 浏览器验证
  norms_browser.html
```

### Step 2 详解：坐标聚类 + 列对齐

**输入**：`page_XXXX.json`（PyMuPDF text+coordinate）

**输出**：`clustered/page_XXXX.json`

```json
{
  "page": 47,
  "subsection": "四、人力挖地槽、地坑土方",
  "work_content": "挖土，修整边坡及底面，制作、安装及拆除挡土板，原土夯实。",
  "unit": "100m³",
  "is_continued": false,
  "code_columns": [
    {
      "code": "10018",
      "x": 313.4,
      "header_texts": [
        {"text": "地槽", "y": 97.4},
        {"text": "无挡土板", "y": 111.6},
        {"text": "土壤类别", "y": 125.6},
        {"text": "Ⅰ～Ⅱ", "y": 139.8}
      ]
    },
    {
      "code": "10019",
      "x": 378.8,
      "header_texts": [
        {"text": "地槽", "y": 97.4},
        {"text": "无挡土板", "y": 111.6},
        {"text": "Ⅲ～Ⅳ", "y": 139.8}
      ]
    }
  ],
  "data_rows": [
    {
      "seq": 1,
      "name": "人工",
      "unit": "工日",
      "code": "192000010001",
      "values": {"10018": 10.37, "10019": 21.38, "10020": 12.96, "10021": 26.57}
    },
    {
      "seq": 2,
      "name": "板枋材",
      "unit": "m³",
      "code": "190503002020",
      "values": {"10018": null, "10019": null, "10020": 0.71, "10021": 0.34}
    }
  ]
}
```

**聚类算法**（确定性，不依赖AI）：

1. **行分组**：按y坐标（±5 tolerance）将文本块分组为行，行内按x排序
2. **页面元数据提取**：从顶部行提取subsection标题、工程内容、单位
3. **定额编号列检测**：找到包含"定额编号"的行，提取所有5位数字作为列标识
4. **列边界计算**：以相邻定额编号的中点作为列边界，覆盖所有表头行
5. **列内文本收集**：表头区域（定额编号行以上）的每个文本块，按x坐标分配到相应列
6. **数据行识别**：以序号(1,2,3...)开头的行作为数据行
7. **数值→列匹配**：数据行中的数值按x坐标匹配到最近的定额编号列

这一步完全不需要AI，100%确定性的坐标运算。

### Step 3 详解：AI语义理解

**输入**：`clustered/page_XXXX.json`（列对齐后的结构化数据）

**AI任务**：理解每列表头文本序列的语义，输出属性维度和费用项目

**为什么Step 2的输出已经足够AI理解？**

P47的clustered数据发给AI后，AI看到的不是原始坐标，而是已经组织好的结构：

```
页面: P47
标题: 四、人力挖地槽、地坑土方
工程内容: 挖土，修整边坡及底面，制作、安装及拆除挡土板，原土夯实。
单位: 100m³
续表: false

列1 (定额编号 10018): [地槽, 无挡土板, 土壤类别, Ⅰ～Ⅱ]
列2 (定额编号 10019): [地槽, 无挡土板, Ⅲ～Ⅳ]
列3 (定额编号 10020): [地坑, 有挡土板, Ⅰ～Ⅱ]
列4 (定额编号 10021): [地坑, 有挡土板, Ⅲ～Ⅳ]

数据行:
  1. 人工 (工日, 192000010001) → 10018:10.37, 10019:21.38, 10020:12.96, 10021:26.57
  2. 板枋材 (m³, 190503002020) → 10018:-, 10019:-, 10020:0.71, 10021:0.34
  ...
```

AI从中很容易推断：第1个属性叫"开挖类型"（值：地槽/地坑），第2个属性叫"支护方式"（值：无挡土板/有挡土板），第3个属性叫"土壤类别"（值：Ⅰ～Ⅱ/Ⅲ～Ⅳ）。注意"土壤类别"跨列出现——它在某些列上方作为标签，而实际值在下层。

**AI Prompt设计**：

```
你是一个工程造价定额数据的结构化提取器。

给你一页定额表的列对齐数据。每列的header_texts是从上到下的表头文本序列。
数据行中，values是每列对应的数值（null表示"—"或空白）。

请输出这个页面的完整1D结构化数据。

## 输出格式

{
  "page_type": "norms_table | continued_table | non_table",
  "subsection": "<分项标题，如'四、人力挖地槽、地坑土方'>",
  "work_content": "<工程内容文字>",
  "unit": "<表的整体计量单位，如'100m³'>",
  "attr_dimensions": [
    {"name": "<属性名>", "values": ["<列1的值>", "<列2的值>", ...]}
  ],
  "cost_items": [
    {"name": "<费用项目名>", "unit": "<单位>", "code": "<代码>"}
  ],
  "items": [
    {
      "norms_code": "10018",
      "attr_<属性名1>": "<值>",
      "attr_<属性名2>": "<值>",
      "<费用项目名>": <数值或null>,
      ...
    }
  ]
}

## 关键规则

1. **属性不遗漏**：header_texts中除"定额编号"外的每个层级分类都要提取为独立属性维度。
   识别方法：如果某文本在列间取值不同（如列1="地槽"、列3="地坑"），它是属性值。
   如果某文本在所有列相同（如列1~4都="土壤类别"），它是属性名标签。
   跨列重复的文本通常是属性名（描述了下方属性值的含义）。

2. **属性名用中文**：从表头文本中提取或推断。如看到"地槽"/"地坑"→属性名"开挖类型"。
   如看到"无挡土板"/"有挡土板"→属性名"支护方式"。
   如看到"Ⅰ～Ⅱ"/"Ⅲ～Ⅳ"→属性名"土壤类别"。
   如看到"2.0"/"3.0"且上方有"斗容"字样→属性名"斗容(m³)"。
   如看到"孔深80m"/"孔深100m"→属性名"孔深"，值分别为"80m"/"100m"（融合标签拆分）。

3. **每个定额编号 × 每行费用项目 = 一条记录**。n个定额编号 × m个费用项目 = n×m条items。

4. **null ≠ 0**：表格中的"—"、"－"、空白输出null，不填0。

5. **续表处理**：page_type="continued_table"时，只输出items，不重复attr_dimensions和cost_items。
   续表继承前一页的subsection/work_content/unit/attr_dimensions/cost_items。

6. **同名费用项目区分**：如果同名费用项目出现多次且单位不同（如"其他材料"的单位分别是"元"和"%"），
   在cost_items中分别列出，items中费用项目名改为"其他材料(元)"和"其他材料(%)"。

7. **费用项目单位 vs 表格单位**：unit是整表的计量单位（如100m³），不能填费用项目单位（如工日、元）。

8. **只输出JSON，不要解释。**
```

### 批量处理策略

**串行处理（推荐）**，原因：
- 续表需要前一页的AI输出作为context
- 避免API rate limit
- 每页~500ms延迟，722页约6分钟即可完成

**实际实现**：
```python
def process_all():
    prev_ai_result = None
    for pg in range(44, 915):  # 定额表从P44开始
        clustered = load_clustered(pg)
        if not clustered or not clustered["code_columns"]:
            prev_ai_result = None  # 非表页，中断续表链
            continue
        
        if clustered["is_continued"] and prev_ai_result:
            # 继承前一页的元数据，只发items给AI
            prompt = build_continued_prompt(clustered, prev_ai_result)
        else:
            prompt = build_full_prompt(clustered)
        
        result = call_ai_api(prompt)
        save_extracted(pg, result)
        
        if result["page_type"] == "norms_table":
            prev_ai_result = result
```

**并行优化（可选）**：
- 按章并行：每章内串行，章间并行（不同章不存在续表关系）
- 6个章节 = 6个并发worker，总时间约1分钟

### 费用估算

| 项目 | 估算 |
|------|------|
| 定额表页面数 | ~722页 |
| 每页输入token | ~1500-3000（取决于表复杂度） |
| 每页输出token | ~800-2000 |
| 总输入token | ~1.5M |
| 总输出token | ~1M |
| 预估费用（Claude Haiku） | ~$2-3 |
| 预估费用（Claude Sonnet） | ~$10-15 |
| 预估时间（串行） | ~6-10分钟 |

推荐使用Claude Sonnet，在复杂表头理解上比Haiku更可靠。

## 与现有DB Schema的映射

```
items[].norms_code          → norms_item.norms_code
items[].attr_*              → norms_item.attr_level1~4 + attr1_label~4_label
items[].<费用项目名>        → norms_item.cost_item + amount
cost_items[].unit           → norms_item.cost_item_unit
cost_items[].code           → norms_item.code
page                        → norms_item.page
table_id (按subsection分组)  → norms_item.table_id
subsection                  → norms_table.subsection_title (+ chapter条目)
unit                        → norms_table.unit
work_content                → norms_table.work_content
attr_dimensions             → norms_table.header_json
```

注意：AI输出的属性维度可能超过4个（如P47有3个属性维度，某些机械表可能有5-6个）。超过4个时，前4个存入attr_level1~4/attr1_label~4_label，完整信息保留在header_json中。

## 质量校验

每页AI输出后自动校验：

| 检查项 | 规则 | 处理 |
|--------|------|------|
| 属性完整性 | 同一subsection内所有items的属性字段集合应一致 | 不一致时标记，人工复核 |
| 数值覆盖率 | items中null值占比不应超过50% | 超过时检查是否是续表/未完表 |
| 费用项目一致性 | 同一subsection内cost_items列表应一致 | 续表页面继承前页 |
| items数量 | items数 = norms_codes数 × cost_items数 | 不匹配时检查是否同名合并 |
| 编号连续性 | 定额编号应在合理范围内 | 异常时可能该页误分类 |
| JSON格式 | 必须合法JSON，所有字段齐全 | 解析失败时重试 |

校验失败的处理：
1. 自动重试（用更详细的prompt，包含错误描述）
2. 2次重试仍失败 → 标记为需人工复核
3. 人工复核页面汇总到 `output/review_needed.json`

## 实施步骤

| 步骤 | 内容 | 脚本 | 产出 |
|------|------|------|------|
| 1 | 坐标聚类 + 列对齐 | `scripts/cluster_columns.py` | `output/intermediate/clustered/page_XXXX.json` |
| 2 | AI逐页提取（先跑P44-P100与已知数据对比验证） | `scripts/ai_extract_page.py` | `output/intermediate/extracted/page_XXXX.json` |
| 3 | 质量对比：AI输出 vs 人工配置KNOWN_SECTIONS | 手动对比 | 验证报告 |
| 4 | 调整prompt直到P44-P100全部通过 | 迭代 | 稳定的prompt |
| 5 | 全量提取 P44-P914 | `scripts/ai_extract_page.py` | 722个extracted JSON |
| 6 | 入库 | `scripts/load_extracted_to_sqlite.py` | `jts_norms.sqlite` |
| 7 | 质量抽检 + 浏览器验证 | `norms_browser.html` | 验收报告 |

### Step 1 优先验证

先对P44-P100（已有高质量人工数据）运行Step 2，对比AI输出与KNOWN_SECTIONS定义：

- P47（3属性维度，同名费用项目）——最复杂case
- P44（3属性维度，部分属性仅适用于部分列）
- P49（2属性维度，运距属性）
- P101（autodetect失败，cost_item被识别为数字"15"）

如果这4页AI输出与人工数据一致，则prompt合格，可全量执行。

## 关键文件

| 文件 | 作用 |
|------|------|
| `scripts/extract_text_all.py` | Step 1: 文本+坐标提取（已完成） |
| `scripts/cluster_columns.py` | Step 2: 坐标聚类+列对齐（新建） |
| `scripts/ai_extract_page.py` | Step 3: AI语义理解（新建） |
| `scripts/load_extracted_to_sqlite.py` | Step 4: 入库（已有，需适配） |
| `temp/scripts/extract_all_tables.py` | 参考：KNOWN_SECTIONS人工定义（P44-100） |
| `temp/scripts/extract_auto.py` | 参考：现有自动提取逻辑（将被替换） |
| `output/intermediate/text/page_XXXX.json` | Step 1产出，Step 2输入 |
| `output/intermediate/clustered/page_XXXX.json` | Step 2产出，Step 3输入 |
| `output/intermediate/extracted/page_XXXX.json` | Step 3产出，Step 4输入 |
| `output/db/jts_norms.sqlite` | 最终数据库 |
| `norms_browser.html` | 前端浏览器 |
