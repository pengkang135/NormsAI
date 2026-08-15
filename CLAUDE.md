# CLAUDE.md — Norms-AI

This file instructs Claude Code how to work with this subproject. Read it before any task.

## 项目定位

**定额数据库仓库 + 查询前端**。数据库结构已定型、定额编制主体工作已完成，当前处于**维护模式**：修补数据、增补册次/章节、扩充翻译与术语。

日常操作走**专用技能**（`pk-norms-*` / `pk-boq-*`），不要重新造脚本。`scripts/` 下多为一次性建库脚本，属历史产物，缺失或不可运行不影响日常工作。

`db/` 有独立的 `CLAUDE.md`（读写规则、统一 schema）和 `INDEX.md`（库清单与行数统计），**动 db/ 前先读那两份**。

## 日常任务路由

| 任务 | 走什么 |
|------|--------|
| 查定额、套价、清单匹配 | sqlite MCP 直查 `db/`，或 `pk-norms-match` |
| 导出综合单价表 Excel | `pk-norms-export` 技能（底层 `src/export_norms.py` + `/api/export`） |
| 套定额结果回写主清单 | `pk-norms-apply` 技能 |
| 新定额书入库（PDF） | `pk-norms-import` 技能 |
| 新定额书入库（Excel） | `pk-norms-import-excel` 技能 |
| BOQ 清单类操作 | `pk-boq` 入口技能，由它分发到 `pk-boq-*` 子技能 |
| 浏览/校对定额库 | `python start.py` |
| 改 db/ 前后 | `python scripts/backup_db.py`，并按 `db/CLAUDE.md` 落 `db/backup/` 备份 |

## 目录结构

```
Norms-AI/
├── start.py                  # 主入口：HTTP 服务 + /api/ 直查 SQLite（端口 8080）
├── restart.py                # 杀进程重启
├── config.py                 # 路径常量 + 历史 PDF 管线的 DB_SCHEMA
├── db/                       # 定额数据库仓库（见 db/CLAUDE.md）
│   ├── 企业定额_A~E册.sqlite   # 主引用源，5 册统一 schema
│   ├── glossary.sqlite       # 中英术语库
│   ├── refers/               # 行业/地方定额、项目专用库
│   └── backup/               # 结构性变更前的备份
├── src/                      # 可复用模块（export_norms 导出、ocr_engine、附录表渲染）
├── scripts/                  # 历史建库脚本（见文末「历史管线」）
├── output/                   # 前端 HTML + 导出 JSON + OCR 缓存
├── intermediate/             # PDF 提取中间产物（gitignore，历史）
├── plan/                     # 方案设计文档（不参与运行）
└── temp/                     # 临时脚本与数据（gitignore）
```

## 主入口 start.py

```bash
python start.py              # 端口 8080，打开 output/norms_browser.html
python start.py --port 9000
python restart.py            # 杀掉占用进程后重启
```

前端不预导出 JSON，直接走 `/api/` 端点查 SQLite。库的注册表是 `start.py` 的 `DOC_TO_DB`（doc_key → db/ 下的相对路径）。**新增库只需在此登记**，并按 schema 归入对应集合：

| 集合 | 含义 |
|---|---|
| `ENT_BOQ_DOC_KEYS` | 企业定额 A~E 册（清单层 + Norm/Content/Consumption） |
| `BJ_DOC_KEYS` | 北京2012 系列（无 `_EN` 扩展列、无清单层表） |
| `BJ2021_DOC_KEYS` | 北京2021 |
| 其余 | JTS 等 norms_table/norms_item schema 的库 |

API 端点：`/api/index`、`/api/items`、`/api/nrm-index`、`/api/nrm-items`、`/api/text`、`/api/text-html`、`/api/notes`、`/api/table-header`、`/api/export`。

## 两套数据库 schema

**不要混用**。判断依据：有没有 `Norm` 表。

### A. 企业定额 schema（`db/企业定额_A~E册`，主引用源）

清单层 `division` / `sub_division` / `enterprise_item` / `nrm_item`，定额层 `chapter` / `Norm` / `Consumption` / `Content` / `norm_source`。翻译列 convention：中文源加 `_EN`，英文源加 `_ZH`。字段明细见 `db/CLAUDE.md`。

增补定额时要同时维护：`chapter` 挂树（`chap_PID`）、`Norm` 编号前缀（BJ12./BJ21. 等来源标识）、`Content` 连接表、`Consumption` 去重复用、`norm_source` 溯源。

### B. PDF 提取 schema（`config.py` `DB_SCHEMA`，9 张表）

仅用于 `refers/` 下由 PDF 提取的库（JTS、北京2012 等）：

| 表 | 用途 | 关键字段 |
|----|------|---------|
| `document` | 文档元数据 | title, doc_number, total_pages |
| `chapter` | 四级章节层级 | parent_id (自引用), level, title, start_page, end_page |
| `page_index` | **中枢表**，每页索引 | page_type, chapter_id, table_id, appendix_id |
| `section_text` | 说明文字/目录/公告 | chapter_id, page, type, content |
| `norms_table` | 定额表元数据 | chapter_id, header_json, unit, row_count |
| `norms_item` | 定额条目(1D长格式) | norms_code, attr_level1~4, cost_item, amount |
| `appendix_table` / `appendix_row` | 附录表格 | table_name, data_json |
| `ocr_block` | OCR 原始块 | page, x1~y2, text, confidence |

## 多维表转一维的核心规则

新增定额书时仍适用（详见 `plan/多维表转一维skill.md`）：

1. 每个 5 位定额编号 = 一列 → 转为一个 `norms_code`
2. 多级表头属性（土壤类别、斗容、吨位等）→ 解析为 `attr_level1~4`
3. 每行费用项目（人工、材料、机械、基价等）× 每个定额编号 = 一条 `norms_item`
4. 隐式属性推断：识别 "Ⅰ类土"、"Ⅱ类土" 等分类标签，自动推断属性名
5. 融合标签拆分："孔深100m" → 属性名"孔深" + 属性值"100m"
6. 合并值拆分：PDF 渲染将多列数值合并为一个文本片段时，按左边缘坐标拆分

## 历史管线（已完成，仅供追溯）

企业定额 A~E 册和 `refers/` 各库均已建成入库，以下脚本**不需要再跑**；重跑会覆盖已人工校准的数据。新书入库一律走 `pk-norms-import` / `pk-norms-import-excel` 技能。

- **企业定额建库**：`build_enterprise_norms_A_full.py`、`build_enterprise_norms_C_full.py`、`import_pk_to_A.py`、`append_2021_norms.py`、`append_missing_norms.py`、`merge_2021_and_prefix.py`、`match_2021_norms_to_existing[_C].py`、`llm_semantic_match.py`
- **文本型 PDF 提取**（坐标聚类 + AI 语义）：`extract_text_jts.py` → `cluster_columns.py` → `ai_extract_jts.py` → `validate_extraction.py` → `build_md_jts.py` → `load_jts_to_sqlite.py` → `export_jts_json.py`
- **图片型 PDF 提取**（OCR）：`ocr_all.py` → `prescan.py` → `gen_agent_prompts.py` → `text_to_md.py` → `process_ch5_6_v5.py` → `load_md_to_sqlite.py` → `verify_md.py`
- **ent_norms 骨架线**（独立于 db/ 主库，产出 `output/ent_norms.sqlite`）：`scripts/enterprise/` 下 `init_ent_schema` → `load_bj2012`/`load_jts276`/`load_wbs` → `tag_discipline` → `verify_skeleton` → `export_browser_json`，用 `python -m scripts.enterprise.xxx` 调用

仍在用的模块：`src/export_norms.py`（Excel 导出）、`src/ocr_engine.py`、`src/appendix_tables/`（前端附录表渲染）、`scripts/backup_db.py`。

## 参考文档

| 文档 | 内容 |
|------|------|
| `db/CLAUDE.md` | db/ 读写规则、企业定额 5 册统一 schema、术语库 |
| `db/INDEX.md` | 各库范围与行数统计 |
| `plan/多维表转一维skill.md` | 多维表头展平算法详解 |
| `plan/文本型PDF提取方案.md` | 文本型 PDF 的 pipeline 说明 |
| `plan/按书本结构提取数据的通用方案.md` | 结构/内容分离设计 |
| `plan/实施计划_图片型PDF.md` | 图片型 PDF 的 OCR 提取方案 |
| `plan/多Agent并行方案_图片型PDF.md` | 图片型 PDF 的多 Agent 并行策略 |
| `plan/troubleshooting/` | 图片型/文本型 PDF 的已知问题修复记录 |
| `plan/norms_browser_reference_20260715/` | 前端历史快照，改版时对照 |

## 常用命令

```bash
cd Norms-AI

# 启动/重启浏览器
python start.py
python restart.py

# 数据库备份（改 db/ 前必做）
python scripts/backup_db.py
```

## 项目文件组织规范

- 临时/调试脚本放 `temp/scripts/`，临时数据放 `temp/`；根目录不放临时文件
- `db/` 只放数据库与备份，不放脚本/日志/中间数据
- `output/` — 前端 HTML、导出 JSON、`ocr/` 缓存
- `intermediate/` — PDF 提取中间产物（历史）
- `plan/` — 方案设计文档，不直接参与运行
