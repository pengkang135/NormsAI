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
├── 企业定额_M册_机械台班定额.sqlite  # 主引用: 机械台班(行业定额schema)
├── 企业定额_N册_材料用量定额.sqlite  # 主引用: 材料用量(行业定额schema)
├── refers/                          # 行业/地方定额、项目专用库
│   ├── 北京2012_*.sqlite
│   ├── 北京2021_*.sqlite
│   ├── norms_jts276-*.sqlite
│   ├── boq_pk_civil_202606.sqlite
│   └── 三航局Laldia项目人工机械定额.sqlite
└── backup/*.bak                     # 备份
```

## 企业定额 A~E 5 册统一 schema（2026-08 起）

A~E 共 5 册对齐以下表名与字段命名 convention（M/N 册例外）：

> M/N 册（机械台班/材料用量）沿用 PDF 提取 schema（`chapter`/`norms_table`/`norms_item`），
> 不适用本统一 schema，详见 `INDEX.md`「M/N 册（行业定额 schema）」。refers/ 保留来源原件。

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
| `Consumption` | 人材机字典（712~4221 行/册） | cons_Name, cons_Standard, cons_Units + `_EN`、master_res_ID、`cons_*_raw` |
| `Content` | 定额×人材机连接表 | norm_ID, cons_ID, cont_Amount |
| `norm_source` | 定额来源溯源（可选） | norm_ID, source_lib, source_book |

**翻译列命名 convention**：源列后缀 `_EN`（中文源加英文）或 `_ZH`（英文源加中文）；保留源列大小写风格。

## 人材机标准化（2026-08 消耗量梳理后）

5 册的 `Consumption` 已按统一标准重整，**唯一事实源是 `resource_master.sqlite`**，各册通过
`Consumption.master_res_ID` 挂靠。新增定额书入库后必须走同一套标准，不要再各册自行其是。

- **名称**：只留基础名，不含规格/单位/来源标记。规格一律进 `cons_Standard`
  （`无缝钢管` + `22*2.5`，不写成 `无缝钢管22*2.5`）。字形描述用「形」
  （`U形轻钢龙骨`），产品型号命名保留「型」（`Y型过滤器`、`U型螺栓`）；
  另用 `黏土`、`箅子`
- **单位**：值域受 `resource_master.unit_norm` 约束（72 种）。`m²`/`m³` 一律写 `m2`/`m3`
- **分类**：`cons_Style` 3=人工 4=材料 5=机械 6=设备 7=主材，`kind_Code` 前缀
  01/02/03/04/05 与之一一对应（06=配比半成品，跨 4/5）
- **人工**：只取 杂工 / 普工 / 技工 / 高级技工 / 工长 五级，工种写进 `cons_Standard`
- **单价**：价格事实源是 `resource_master.resource_price`，PK `(res_ID, pack, price_date)`，
  按**价格包**承载（`pack` 见下节）。列里的 `country` 是**报价来源国**，不是价格归属，
  过滤价格一律用 `pack`，不要用 `country`。2026-08 起各册 `Consumption.cons_Price`(THB)/
  `cons_Market`(CNY) 与 `Norm` 6 个价格列已回写「泰国参考基价」，不再是清 0 状态。
- **费率型条目**（其他材料费/其他机具费/补差，单位 % 或 元）已删除，不再入库
- `cons_Name_raw` / `cons_Standard_raw` / `cons_Units_raw` 是梳理前的原值，仅供回滚追溯

**改动 `Consumption` 的红线**：消耗量守恒。对任一 `(定额, master_res_ID)`，
`Σ(cont_Amount × 单位换算系数)` 不得变化；只有单位换算、同资源合并累加两种情形可动
`cont_Amount`。

## 价格包 `price_pack`（2026-08 起）

一个包 = 一套定价结论。`price_pack(pack, name, name_EN, country, currency, fx_json,
cutoff_date, status, note)` 是注册表，`resource_price.pack` 挂靠。当前只有 `th_2026`
（泰国 / THB / `{"CNY":5.0}` / status=active），10,191 行全归它。

`resource` / `price_quote` / `quote_match` / `price_anchor` **跨包共享**——资源主数据和
原始报价不分包，只有定价结论分包。新增国家包 = 插一行 `price_pack` + 灌该 pack 的
`resource_price`，不复制主数据。

前端价格库与 `src/export_norms.py` 都按 `status='active'` 取默认包。

## 使用台账 `resource_usage`

五册 `Consumption` → 主数据的使用台账，16,912 行 / 13,780 个资源，供价格库分册导航与
引用次数统计。`cons_Style` / `kind_Code` / `cons_Name` 取**分册视角**的值（同一资源在
A 册是材料、B 册可能是主材）。**各册数据更新后须重跑** `python scripts/build_resource_usage.py`。

## 泰国参考基价口径（2026-08）

以 CostSpread 泰国报价为锚、中国基价为底，做的一版**截止 2026 年泰国参考基价**。要求可参考、可追溯，不要求精确。
方案与脚本在 `plan/基价方案/`，验证报告 `output/pricing/report.html`。

- **币种**：THB 为记录本位（写入 `Consumption.cons_Price`），另存 CNY 等值（`cons_Market`）。
- **换算**：`FX_THB_PER_CNY = 5.0`（假设值，未核实 2026 实际汇率）。改汇率需重跑 Phase 3~5。
- **系数**：锚点标定分类系数——人工 0.781 / 材料 0.993 / 机械 0.916，另按族细分（汽车起重机族 0.769、钢筋族 0.993、技工族 0.781），存 `resource_master.price_factor`。
- **人工**：泰国劳动部「技能标准最低工资」1/2/3 级中位数（400/505/602 THB/天）→ 普工/技工/高级技工，乘 `LABOR_ESCALATION=1.30` 推到 2026；工长按中国 工长/高级技工 比例 1.83 外推。
- **机械**：泰国租赁「台月 ÷ 26 班」折算台班，假设租赁价已含机上人工（`OPERATOR_UPLIFT=1.0`），不含燃料。
- **留空**：主材/设备（中国定额惯例「未计价材料」）+ 艘班/组日（无源可补），留空并进 `review_queue`，不编造数字。
- **派生层级**：L1 锚点直接 / L2 中国基线×FX×系数 / L3 近重名 / L5 同类同单位中位数，`source` 列记录层级与依据。L5 最粗糙，头部异常项（渣土消纳、土方运输等）待人工复核。
- **语义变更**：`Norm` 6 个价格列含义从「来源书中国基价」变为「泰国基价」，旧值已快照到 `resource_master.norm_price_legacy`（6 库 `*.pre-pricing-*.bak` 另存原样）。

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
