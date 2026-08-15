# 定额数据库索引

> 本项目内可写；外部项目调用只读。见 `CLAUDE.md`。

## 主引用源 — 企业定额 5 册（统一 schema）

| 文件 | 范围 | division | sub_division | enterprise_item | nrm_item | chapter | Norm | Consumption |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `企业定额_A册_建筑装饰.sqlite` | 建筑装饰 | 22 | 98 | 599 | 478 | 678 | 5780 | 4090 |
| `企业定额_B册_通用安装.sqlite` | 通用安装 | 14 | 136 | 1188 | 85 | 1338 | 12470 | 4091 |
| `企业定额_C册_市政园林.sqlite` | 市政园林 | 15 | 64 | 825 | 62 | 1019 | 14369 | 6772 |
| `企业定额_D册_水运工程.sqlite` | 水运工程 | 10 | 22 | 404 | 0 | 471 | 3769 | 888 |
| `企业定额_E册_房屋修缮.sqlite` | 房屋修缮 | 13 | 0 | 0 | 0 | 1637 | 13534 | 4245 |

统一表名详见 `CLAUDE.md#企业定额-4-册统一-schema`。

## 术语库

- `glossary.sqlite` — 中英双向术语库，35,194 行。分类：`norm_name`(21,694)、`chapter_name`(4,311)、`nrm_item_name`(487)、`section_title`(38)、`enterprise_item_name`(2,877)、`division_name`(61)、`sub_division_name`(318)、`consumption_name`(5,408)。含 NRM 英标术语（已回填中文）+ 现有 `norm_Name_EN`/`chapter_EN` 提取的双语对 + 翻译新增的企业清单层与人材机名称对

## 行业/地方定额（`refers/` 子目录）

- `refers/北京2012_建设工程计价依据_预算定额.sqlite` — 北京 2012 预算定额（土建为主）
- `refers/北京2012_房屋修缮工程计价依据_预算定额.sqlite` — 北京 2012 房修定额
- `refers/北京2021房屋建筑与装饰工程预算消耗量定额.sqlite` — 北京 2021 定额
- `refers/norms_jts276-1-2019_excel.sqlite` — JTS/T 276-1-2019 沿海港口水工建筑
- `refers/norms_jts276-3-2019_excel.sqlite` — JTS/T 276-3-2019 沿海港口疏浚
- `refers/JTST 271-2020 水运工程工程量清单计价规范.sqlite` — JTS/T 271-2020 清单计价

## 项目专用（`refers/` 子目录）

- `refers/三航局Laldia项目人工机械定额.sqlite` — Laldia 项目人工/机械消耗量
- `refers/boq_pk_civil_202606.sqlite` — BOQ 土建清单匹配结果

## 备份

`backup/{原文件名}.{YYYYMMDD_HHMMSS}.bak` — 每次结构性变更前自动落地
