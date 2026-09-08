# 定额数据库索引

> 本项目内可写；外部项目调用只读。见 `CLAUDE.md`。

## 主引用源 — 企业定额 7 册

| 文件 | 范围 | division | sub_division | enterprise_item | nrm_item | chapter | Norm | Consumption |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `企业定额_A册_建筑装饰.sqlite` | 建筑装饰 | 20 | 107 | 593 | 478 | 683 | 4840 | 2772 |
| `企业定额_B册_通用安装.sqlite` | 通用安装 | 14 | 136 | 1188 | 85 | 1338 | 12470 | 4050 |
| `企业定额_C册_市政园林.sqlite` | 市政园林 | 15 | 64 | 825 | 62 | 1019 | 14362 | 5185 |
| `企业定额_D册_水运工程.sqlite` | 水运工程 | 10 | 22 | 404 | 0 | 471 | 3769 | 708 |
| `企业定额_E册_房屋修缮.sqlite` | 房屋修缮 | 13 | 0 | 0 | 0 | 1637 | 13534 | 4197 |

### M/N 册（行业定额 schema，非统一 schema）

| 文件 | 范围 | chapter | norms_table | norms_item |
|---|---|---:|---:|---:|
| `企业定额_M册_机械台班定额.sqlite` | 机械台班（山东2008 2026修正） | 608 | 474 | 8252 |
| `企业定额_N册_材料用量定额.sqlite` | 材料用量（JTS/T 277-2019 配比材料 + 混凝土构件模板钢筋含量） | 62 | 71 | 3612 |

M/N 册沿用 PDF 提取 schema（`chapter`/`norms_table`/`norms_item`），未转 A~E 的统一 schema；
`refers/` 下保留来源原件。未来可在 M 册补非山东机械台班、N 册补非 JTS277 材料用量数据。

统一表名详见 `CLAUDE.md#企业定额-5-册统一-schema`。`Consumption` 行数已按
`CLAUDE.md#人材机标准化` 去重合并（原 20,086 → 17,027）。

## 人材机主数据 `resource_master.sqlite`

跨 5 册的人材机唯一标准，各册用 `Consumption.master_res_ID` 挂靠。

| 表 | 行数 | 说明 |
|---|---:|---|
| `resource` | 13,981 | 标准条目：类别 / 基础名 / 规格 / 单位 + 中英对照 |
| `resource_alias` | 20,042 | 各册每一行的原始写法 → 标准条目，含单位换算系数（含去重前的历史别名） |
| `resource_usage` | 16,912 | 五册在用 `Consumption` → 主数据的使用台账，带分册视角分类与引用次数 |
| `resource_price` | 10,191 | 定价结论，PK `(res_ID, pack, price_date)`，当前全部 `pack='th_2026'`（THB） |
| `price_pack` | 1 | 价格包注册表：`th_2026` 泰国参考基价 2026 / THB / active |
| `price_quote` | 13,421 | 原始报价：名称/规格/单位/国别/币种/含税不含税/日期/供应商/来源文件/专业/tier |
| `quote_match` | 11,728 | 资源 ↔ 原始报价的候选匹配（match_type + confidence），覆盖 1,441 个资源 |
| `price_anchor` | 31 | 泰国锚点（CostSpread 报价），含仅标定用的包干费率 |
| `price_factor` | 26 | 标定系数：人工/材料/机械 + 族级（汽车起重机、钢筋、技工） |
| `unit_norm` | 23 | 单位归一表（符号变体 + 量级倍数） |
| `review_queue` | 170 | 待人工复核项（规格未译、单位推定、异体字未合并） |
| `norm_price_legacy` | 48,975 | `Norm` 6 个价格列的旧中国基价快照（回写泰国基价前留存） |

**价格覆盖率**（按册×类别，`resource_usage` × `resource_price`）：人工五级 100%；
A 材料 81.2% / 机械 74.5%；B 材料 100% / 机械 99.7% / **设备 3.9% / 主材 15.8%**；
C 材料 85.7% / 机械 84.0% / 主材 12.5%；**D 材料 25.4% / 机械 23.2%**（艘班全缺）；
E 材料 100% / 主材 11.7%。无价但被定额引用的资源 3,787 条、53,261 次引用。

来源可靠度（`tier`）：T1 泰国直采 41 / T2 邻国 387 / T3 中国 792 / T4 非洲 221 /
S 近似重名 535 / D 派生 8,215。

英译覆盖：名称 100%、单位 100%、规格 96.3%。

价格包机制见 `CLAUDE.md#价格包-price_pack`：过滤价格用 `pack`，**不要用 `country`**
（那是报价来源国，派生价多为「中国」）。`resource_usage` 在各册数据更新后须重跑
`python scripts/build_resource_usage.py`。

泰国参考基价口径（2026-08）见 `CLAUDE.md#泰国参考基价口径`，要点：THB 本位、`FX_THB_PER_CNY=5.0`、
人工 0.781 / 材料 0.993 / 机械 0.916 系数、主材/设备与艘班留空、`Norm` 旧中国基价快照到 `norm_price_legacy`。

**字形用字约定**：字形描述统一用「形」（`U形轻钢龙骨`、`T形轻钢龙骨吊件`）；
产品型号命名保留「型」（`W型排水铸铁管`、`Y型过滤器`、`U型螺栓`、`A型汇流排线夹`）。
另：`黏土`（非粘土）、`箅子`（非篦子）。

## 术语库

- `glossary.sqlite` — 中英双向术语库，37,086 行。分类：`norm_name`(21,694)、`consumption_name`(7,300)、`chapter_name`(4,311)、`enterprise_item_name`(2,877)、`nrm_item_name`(487)、`sub_division_name`(318)、`division_name`(61)、`section_title`(38)。含 NRM 英标术语（已回填中文）+ 现有 `norm_Name_EN`/`chapter_EN` 提取的双语对 + 翻译新增的企业清单层与人材机名称对

## 行业/地方定额（`refers/` 子目录）

- `refers/北京2012_建设工程计价依据_预算定额.sqlite` — 北京 2012 预算定额（土建为主）
- `refers/北京2012_房屋修缮工程计价依据_预算定额.sqlite` — 北京 2012 房修定额
- `refers/北京2021房屋建筑与装饰工程预算消耗量定额.sqlite` — 北京 2021 定额
- `refers/norms_jts276-1-2019_excel.sqlite` — JTS/T 276-1-2019 沿海港口水工建筑
- `refers/norms_jts276-3-2019_excel.sqlite` — JTS/T 276-3-2019 沿海港口疏浚
- `refers/norms_jts277-2019_配比材料.sqlite` — JTS/T 277-2019 水运工程混凝土和砂浆材料用量定额（配比展开：半成品→水泥/砂/石/水/外加剂，41 表 / 2241 条）。**已提升为企业定额 N 册材料用量定额，此处为来源原件副本**
- `refers/JTST 271-2020 水运工程工程量清单计价规范.sqlite` — JTS/T 271-2020 清单计价
- `refers/山东2008机械台班定额_2026修正.sqlite` — 山东 2008 机械台班定额（2026 修正），947 子目 / 12 大类 / 122 子类 / 474 机械类型（三级章节导航：大类→子类→机械类型；每类型一张表，详情页为费用组成 8 项 + 消耗量 7 项的横向子目对比表）。**已提升为企业定额 M 册机械台班定额，此处为来源原件副本**

## 项目专用（`refers/` 子目录）

- `refers/三航局Laldia项目人工机械定额.sqlite` — Laldia 项目人工/机械消耗量
- `refers/boq_pk_civil_202606.sqlite` — BOQ 土建清单匹配结果

## 备份

`backup/{原文件名}.{YYYYMMDD_HHMMSS}.bak` — 每次结构性变更前自动落地
