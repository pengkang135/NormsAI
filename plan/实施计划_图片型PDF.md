# 图片型PDF定额提取 — 实施计划

## 适用范围

扫描版（图片型）PDF定额文件。此类PDF每页为一个完整图像，无嵌入式文本层，必须通过OCR获取文字和坐标。

## 核心思路

放弃通用脚本逐页解析表格。采用 **OCR提取文字+坐标 → AI理解布局 → 输出Markdown → 入库SQLite** 的流水线。

```
PDF → [OCR引擎多pass识别] → [AI读取OCR JSON，理解布局，展开表头] → output/md/page_XXXX.md → load_md_to_sqlite.py → SQLite
```

- **OCR**: 机械任务，由 `src/ocr_engine.py` 完成，多pass识别+Iou去重
- **AI理解**: case-by-case处理，逐个页面/节理解布局和表格结构
- **入库**: 机械任务，纯脚本，由 `scripts/load_md_to_sqlite.py` 完成

## 前置条件

1. 已有可工作的OCR引擎（`src/ocr_engine.py`）
2. 已配置 `config.py`：`PDF_PATH`、`DEFAULT_PAGE_RANGE`、`DB_SCHEMA`
3. 已准备参考格式样本（gold set）用于验证输出格式

## 实现步骤

### Step 1: 全量OCR

**脚本**: `scripts/ocr_all.py`

遍历PDF全部页面，调用OCR引擎识别，缓存结果到 `output/ocr/ocr_{XXXX}.json`。

- 支持断点续跑（检测已有缓存跳过）
- 使用 `src/ocr_engine.py` 的 `ocr_page()` 函数
- 每页预估5-8秒（取决于OCR pass数和分辨率）
- Gold set页面优先处理，用于后续格式验证

### Step 2: 页面分类

**脚本**: `scripts/classify_pages.py`

根据OCR文本自动分类每页类型，输出 `output/page_index.json`。

分类类型：
| 类型 | 说明 |
|------|------|
| `title_page` | 扉页/封面 |
| `toc` | 目录页 |
| `chapter_divider` | 章节分隔页 |
| `chapter_text` | 章节说明/正文页 |
| `norms_table` | 定额数据表 |
| `appendix` | 附录表 |
| `blank` | 空白/近似空白页 |

### Step 3: AI逐节转换Markdown（核心步骤）

> **并行化方案详见**: `plan/多Agent并行方案_图片型PDF.md` — 按"节"分派 agent，节内串行，节间并行。

**工作流程**：
1. AI读取 `output/ocr/ocr_XXXX.json`（含文字+坐标）
2. 从坐标理解页面布局，识别：章节标题 → 分项标题 → 工程内容 → 表头区 → 数据区
3. 将多维表头展开为扁平行（每个定额编号×每个费用项目 = 一行）
4. 应用领域知识修正OCR错误（参见 `references/` 中的领域知识参考）
5. 输出 `output/md/page_XXXX.md`

**Markdown输出格式**：
```markdown
---
page: {页码}
type: norms_table
chapter: {章节名}
section: {节名}
continued_from: {前页页码或null}
---

# 第{页码}页

## {表格标题}

- **工程内容**: {工程内容描述}
- **单位**: {单位}

| 定额编号 | 分部工程 | 分项工程 | 属性1 | ... | 费用项目 | 单位 | 数量 |
|:---|:---|:---|:---|:---|:---|:---:|---:|
| {code} | {part} | {sub} | {attr} | ... | {item} | {unit} | {amount} |
```

**表格规则**：
- 每个定额编号 × 每个费用项目 = 一行
- 定额编号列在每行都出现（不合并单元格）
- 基价始终是该组定额编码的最后一行
- 空值为 `—`（全角破折号），表示该组合不适用
- 续页标记 `（接前页）`

**分批处理策略**：

按章节/节分批，每批完成后验证再进入下一批：
1. Gold set页面优先，验证格式正确性
2. 扉页+说明+目录
3. 各章定额表，按章节顺序推进
4. 附录

### Step 4: SQLite入库

**脚本**: `scripts/load_md_to_sqlite.py`

- 解析Markdown的YAML frontmatter → `page_index`, `chapter`, `norms_table`
- 解析Markdown表格 → `norms_item`（定额编号→norms_code, 费用项目→cost_item, 数量→amount等）
- 先写入 `staging.sqlite`，验证后合并到主库
- Target schema: `config.py` 中定义的 `DB_SCHEMA`

### Step 5: 验证

**脚本**: `scripts/verify_md.py`

| 检查项 | 方法 |
|:---|:---|
| Markdown文件数 | 文件计数 vs 预期页数 |
| 定额编号列无空值 | 解析MD表格 |
| 数量列均为有效数字或占位符 | 解析数值列 |
| Gold set与基准一致 | 对比参考格式 |
| 章节覆盖完整 | 与目录页对照 |
| 定额编号连续性 | 按章节检查编号范围 |
| 基价覆盖率 | 每个定额编组至少一行基价 |

## 关键能力

1. **从OCR坐标理解表格**：通过x对齐判断列归属，y分层判断表头/数据行关系
2. **多维表头展开**：识别定额编号列→属性分组列→费用项目列，展开为扁平行
3. **OCR错误修正**：补漏字、乱码修复、罗马数字归一化，需针对具体定额准备领域知识修正表
4. **续表处理**：识别"续表"/"续前表"标记，继承前页表头和上下文
5. **并排表处理**：通过y坐标gap分离独立表格区域，检测左右并排布局
6. **跨页连续性**：检测定额编号序列的跨页连续性，识别遗漏或重复

## 配置要求

`config.py` 需配置：
```python
PDF_PATH           # 图片型PDF路径
DEFAULT_PAGE_RANGE  # 页面范围
GOLD_SET_PAGES      # 验证用基准页面
OCR_RENDER_SCALE    # OCR渲染分辨率
OCR_CONFIDENCE_THRESHOLD  # 置信度阈值
OCR_MULTI_PASS      # OCR多pass参数
```
