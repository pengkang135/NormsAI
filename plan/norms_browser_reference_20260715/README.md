# norms_browser 参考模板（2026-07-15 备份）

## 用途

**这是经过验证的"正确框架"备份。** 后续任何改动都不许污染这里的文件；如果 `output/` 下的浏览器被改乱了，从这里复制回去即可还原。

## 内容

| 文件 | 大小 | 说明 |
|---|---|---|
| `norms_browser.html` | 68 KB | 前端页面 — 左侧章节树 + 右侧详情，样式典雅（Noto Serif SC 字体、米黄背景） |
| `norms_index.json` | 616 KB | 定额索引数据 — 章节树 / 定额表 / 页面 / 编号索引 |
| `structure_full.json` | 155 KB | 文档完整结构 — 页面到章节的映射 |

## 数据 JSON 的字段结构

### norms_index.json 顶层字段
- `chapters`: 章节列表 `[{id, parent_id, sort_order, level, title, start_page, end_page}, ...]`
- `tables`: 定额表列表 `[{id, chapter_id, chapter_title, section_title, subsection_title, subsection_clean, work_content, unit, page, seq_on_page, row_count, col_count}, ...]`
- `pages`: 页面清单 `[{page, page_type, chapter_id, chapter_title, table_id, text_preview}, ...]`
- `code_index`: 定额编号 → 页码 `{"10001": 44, ...}`

### structure_full.json 顶层字段
- `document`: 文档元数据
- `page_map`: 每页的分类（cover/toc/norms_table/...）
- `chapters`: 章节树
- `internal_to_pdf`: 原书页码到 PDF 页码的映射

## 版本来源

- 数据源：`db/norms_jts276-1-2019_excel.sqlite`（JTS/T 276-1-2019 沿海港口水工建筑工程定额）
- 前端 HTML 最后修改：2026-07-06 23:54
- JSON 最后修改：2026-06-13
- 本参考副本创建时间：2026-07-15

## 还原方法

```bash
cd E:/Code/Norms-AI
cp plan/norms_browser_reference_20260715/norms_browser.html    output/
cp plan/norms_browser_reference_20260715/norms_index.json      output/
cp plan/norms_browser_reference_20260715/structure_full.json   output/
```

## 后续新库若参考此框架

若为其他源库（北京 2012 主库、修缮库、企业 WBS 定额库）建立同风格浏览器：
1. 复制 `norms_browser.html` 为新文件名（如 `bj2012_main_browser.html`）
2. 按各库的 schema 生成对应的 `*_index.json`（字段名对齐 norms_index.json 的结构约定）
3. **不要** 覆盖 `output/norms_browser.html` 本身
