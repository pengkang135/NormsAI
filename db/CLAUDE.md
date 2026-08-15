# CLAUDE.md — Norms-AI/db 定额数据库目录

## 定位

本目录是**定额数据库仓库**。对外部项目（BOQ 套价、清单询价等）**只读**；对本项目（清单定额、Norms-AI）内部维护**允许写入**——加列、rename、更新翻译、维护 glossary 等操作在此目录进行。

## 规则

- **允许存在**: `.sqlite` 数据库文件、`backup/*.bak` 备份、`INDEX.md`、本 `CLAUDE.md`
- **外部项目**（其他工作目录下的项目）**仅读**：查询走 sqlite MCP / ATTACH，输出到调用方自己的 `temp/`
- **本项目内维护操作**（允许）：schema 变更、翻译列填充、glossary 更新——先备份到 `backup/{文件名}.{时间戳}.bak`
- 禁止在此写入调试脚本、日志、中间数据、截图——只放数据文件

## 目录内容

```
db/
├── CLAUDE.md                        # 本文件
├── INDEX.md                         # 数据库索引
├── glossary.sqlite                  # 中英术语库(NRM+现有翻译种子)
├── 企业定额_A册_建筑装饰.sqlite      # 主引用: 建筑装饰
├── 企业定额_B册_通用安装.sqlite      # 主引用: 通用安装
├── 企业定额_C册_市政园林.sqlite      # 主引用: 市政园林
├── 企业定额_D册_水运工程.sqlite      # 主引用: 水运工程
├── 企业定额_E册_房屋修缮.sqlite      # 主引用: 房屋修缮
├── refers/                          # 行业/地方定额、项目专用库
│   ├── 北京2012_*.sqlite
│   ├── 北京2021_*.sqlite
│   ├── norms_jts276-*.sqlite
│   ├── boq_pk_civil_202606.sqlite
│   └── 三航局Laldia项目人工机械定额.sqlite
└── backup/*.bak                     # 备份
```

## 企业定额 5 册统一 schema（2026-08 起）

所有 5 册对齐以下表名与字段命名 convention：

**清单层**（BOQ 项目字典）
| 表 | 说明 | 关键列 |
|---|---|---|
| `division` | 一级分部（14~22 行/册） | code, name, name_EN, description, description_EN |
| `sub_division` | 二级分部（22~136 行/册） | division_code, sub_code, name, name_EN |
| `enterprise_item` | 企业清单项 GB50500 对齐（409~1188 行/册） | code, name, unit, item_feature, calc_rule, work_content + 对应 `_EN` |
| `nrm_item` | 英标 NRM 清单项（0~478 行/册） | code, name, level_one, level_two, nrm_section_title + 对应 `_ZH` |

**定额层**（人材机消耗量）
| 表 | 说明 | 关键列 |
|---|---|---|
| `chapter` | 定额章节树（531~2294 行/册） | chap_Name, chap_Content, chap_Name_EN |
| `Norm` | 定额子目（3769~12470 行/册） | norm_Code, norm_Name, Norm_Content + `_EN` |
| `Consumption` | 人材机字典（894~4098 行/册） | cons_Name, cons_Standard + `_EN` |
| `Content` | 定额×人材机连接表 | norm_ID, cons_ID, cont_Amount |
| `norm_source` | 定额来源溯源（可选） | norm_ID, source_lib, source_book |

**翻译列命名 convention**：源列后缀 `_EN`（中文源加英文）或 `_ZH`（英文源加中文）；保留源列大小写风格。

## 术语库 `glossary.sqlite`

字段：`term_zh, term_en, category, source, volume, usage_count, notes`

- `source='NRM'` — 英标术语种子（无中文，待补）
- `source='existing_Norm_EN'` — 现有 24K+ `Norm.norm_Name_EN` 反向抽取的双语对
- `source='existing_chapter_EN'` — 现有章节名双语对
- `source='手工'` — 人工新增/修订

用途：翻译新字段时先查 glossary 命中沿用；批量审计一致性（同 zh 多 en 或同 en 多 zh 是可疑项）。

## 查询示例

```sql
-- 外部项目查询
ATTACH 'E:/Code/Norms-AI/db/企业定额_A册_建筑装饰.sqlite' AS a;
SELECT code, name, name_EN FROM a.enterprise_item WHERE division='A.05';

-- 术语查询
ATTACH 'E:/Code/Norms-AI/db/glossary.sqlite' AS g;
SELECT term_zh, term_en FROM g.glossary WHERE term_zh LIKE '%混凝土%';
```
