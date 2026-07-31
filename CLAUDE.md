# CLAUDE.md — Norms-AI

This file instructs Claude Code how to work with this subproject. Read it before any task.

## 项目定位

将**任意格式的定额PDF**（文本型/图片型）结构化提取到SQLite数据库，按原书目录和章节组织，通过浏览器查询。

## 首要步骤：判断PDF类型

**处理任何定额PDF前，必须先判断类型**，再选择对应的提取路径。

```python
import fitz
doc = fitz.open("目标.pdf")
page = doc[10]  # 取一页正文
blocks = page.get_text("dict")["blocks"]
img_blocks = sum(1 for b in blocks if b["type"] == 1)
text_blocks = sum(1 for b in blocks if b["type"] == 0)

if img_blocks == 0 and text_blocks > 0:
    type = "text"     # 文本型 → 走PyMuPDF路径
elif img_blocks > 0 and text_blocks == 0:
    type = "image"    # 图片型 → 走OCR路径
else:
    type = "mixed"    # 混合型 → 按页分派
```

## 两种提取路径

```
                    ┌── 文档结构层 (通用) ──┐
                    │  build_structure.py   │
                    │  目录解析·章节映射·页面分类 │
                    └────────┬──────────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
       文本型PDF路径                    图片型PDF路径
    PyMuPDF直提文本+坐标              PDF渲染+RapidOCR
    extract_text_all.py              ocr_all.py
    table_extractor.py (坐标聚类)     ocr_engine.py
    convert_norms_tables.py          text_to_md.py
              │                             │
              └──────────────┬──────────────┘
                             │
                    ┌────────┴────────┐
                    │  MD文件 (统一格式)  │
                    │  每页一个.md       │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │  load_all_to_sqlite.py │
                    │  → 《沿海港口水工建筑工程定额》(交水发[2004]247号).sqlite  │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │  norms_browser.html  │
                    │  章节导航+表格+搜索    │
                    └─────────────────┘
```

### 路径A：文本型PDF (PyMuPDF)

**适用**: 文本层完整的PDF（如 JTS/T 276-1-2019）

**脚本链**:
| 顺序 | 脚本 | 功能 |
|------|------|------|
| A1 | `scripts/extract_text_all.py` | 全量文本+坐标提取 → `output/text/page_XXXX.json` |
| A2 | `scripts/build_structure.py` | 页面分类+目录解析+章节树 → `output/structure.json` |
| A3 | `scripts/convert_norms_tables.py` | 多维定额表→1D格式MD（调用 `src/table_extractor.py`） |
| A4 | `scripts/convert_text_pages.py` | 目录/说明/公告等文字页→MD |
| A5 | `scripts/generate_all_md.py` | 批量调度A3+A4，生成全部914页MD |

**核心算法**: `src/table_extractor.py` — 从 `temp/scripts/extract_1d.py` 提炼的 `TableExtractor` 类：
- `find_code_columns()` — 5位定额编号列检测
- `parse_header_row_based()` — 多级表头行式解析（属性名/值配对、隐式属性推断、融合标签拆分）
- `parse_data_rows()` — 数据行坐标→列映射、合并值跨列拆分
- `convert_to_1d()` — 多维→一维：每个定额编号×每个费用项目=一条记录

### 路径B：图片型PDF (OCR)

**适用**: 扫描版PDF（如2004版定额）

**脚本链**:
| 顺序 | 脚本 | 功能 |
|------|------|------|
| B1 | `scripts/ocr_all.py` | pypdfium2渲染 + RapidOCR多pass识别 |
| B2 | `scripts/text_to_md.py` | OCR文本→结构化MD |
| B3 | `scripts/prescan.py` | 章节边界预扫描 |

### 通用层（两种路径共用）

| 顺序 | 脚本 | 功能 |
|------|------|------|
| C1 | `scripts/build_structure.py` | 页面分类+目录解析+章节映射（**与PDF类型无关**） |
| C2 | `scripts/load_all_to_sqlite.py` | MD→SQLite全量入库（扩展自 `load_md_to_sqlite.py`） |
| C3 | `scripts/verify_md.py` | MD质量校验 |

## MD文件格式约定

所有页面统一使用以下frontmatter约定（两种路径输出格式一致）：

```yaml
---
page: 80
pdf_page: 80
internal_page: 55               # 原书页码
type: norms_table               # cover|blank|notice|toc|general_instruction|chapter_title|section_intro|norms_table|continued_table|appendix
chapter: "第一章 土石方工程"
section: "第一节 陆上开挖工程"
subsection: "一般土方"
source: pymupdf_text            # pymupdf_text | rapidocr
record_count: 54                # 仅norms_table类型
continued_from: null            # 续表指向首页页码
---
```

定额表的1D格式表头：
```
| 定额编号 | 属性1 | 属性2 | ... | 费用项目 | 单位 | 代码 | 数量 |
```

## 数据库表结构

6张核心表（`config.py` DB_SCHEMA），覆盖完整文档结构：

| 表 | 用途 | 关键字段 |
|----|------|---------|
| `document` | 文档元数据 | title, doc_number, total_pages |
| `chapter` | 四级章节层级 | parent_id (自引用), level, title, start_page, end_page |
| `page_index` | **中枢表**，每页索引 | page_type, chapter_id, table_id, internal_page |
| `section_text` | 说明文字/目录/公告 | chapter_id, page, type, content |
| `norms_table` | 定额表元数据 | chapter_id, header_json, unit, row_count |
| `norms_item` | 定额条目(1D长格式) | norms_code, attr_level1~4, cost_item, unit, code, amount |

**入库顺序**: `document → chapter → page_index → section_text / norms_table → norms_item`

## 关键设计决策

1. **结构与内容分离**: `build_structure.py` 从目录页解析章节树，与底层文本来源无关
2. **多维→一维**: 每个定额编号列×每个费用项目行=一条原子记录，属性值作为附加列
3. **page_index为中枢**: 所有页面通过page_index关联章节和表格，支持按章节范围查询
4. **统一MD格式**: 文本型和图片型输出相同的MD格式，入库脚本通用
5. **续表处理**: `continued_from` frontmatter标记，入库时合并到同一逻辑表

## 多维表转一维的核心规则

（详见 `plan/多维表转一维skill.md`）

1. 每个5位定额编号 = 一列 → 转为一个 `norms_code`
2. 多级表头属性（土壤类别、斗容、吨位等）→ 解析为 `attr_level1~4`
3. 每行费用项目（人工、材料、机械、基价等）× 每个定额编号 = 一条 `norms_item`
4. 隐式属性推断：识别 "Ⅰ类土"、"Ⅱ类土" 等分类标签，自动推断属性名
5. 融合标签拆分："孔深100m" → 属性名"孔深" + 属性值"100m"
6. 合并值拆分：PDF渲染将多列数值合并为一个文本片段时，按左边缘坐标拆分

## 参考文档

| 文档 | 内容 |
|------|------|
| `plan/文本型PDF提取方案.md` | 文本型PDF的完整pipeline说明 |
| `plan/按书本结构提取数据的通用方案.md` | 结构/内容分离设计，适用于两种PDF类型 |
| `plan/多维表转一维skill.md` | 多维表头展平算法详解 |
| `plan/实施计划_图片型PDF_2004版.md` | 图片型PDF的OCR提取方案 |
| `plan/多Agent并行方案_图片型PDF_2004版.md` | 图片型PDF的多Agent并行策略 |
| `plan/问题修复方案_图片型PDF_2004版.md` | 图片型PDF的已知问题修复记录 |

## 常用命令

```bash
cd Norms-AI

# 判断PDF类型
python -c "
import fitz; doc=fitz.open('目标.pdf'); p=doc[10]
blocks=p.get_text('dict')['blocks']
img=sum(1 for b in blocks if b['type']==1)
print('image' if img>0 else 'text')
"

# 全量文本提取（文本型PDF）
python scripts/extract_text_all.py

# 构建文档结构
python scripts/build_structure.py

# 批量生成MD
python scripts/generate_all_md.py

# 入库
python scripts/load_all_to_sqlite.py --md-dir output/md_jts

# 校验
python scripts/verify_md.py --md-dir output/md_jts

# 启动浏览器
python start.py

# OCR单页调试（图片型PDF）
python -c "from src.ocr_engine import ocr_page; ocr_page(42)"
```

## 项目文件组织规范

- 所有临时/调试脚本放入 `temp/scripts/`，数据文件放入 `temp/`
- `output/text/` — 文本提取中间JSON
- `output/md/` — 图片型PDF的MD输出
- `output/md_jts/` — 文本型PDF的MD输出
- `output/ocr/` — OCR缓存JSON
- `plan/` — 方案设计文档（不直接参与运行）
