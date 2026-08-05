# 定额数据库索引

> 本项目内可写；外部项目调用只读。见 `CLAUDE.md`。

## 主引用源 — 企业定额 4 册（统一 schema）

| 文件 | 范围 | division | sub_division | enterprise_item | nrm_item | chapter | Norm | Consumption |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `企业定额_A册_建筑装饰.sqlite` | 建筑装饰 | 22 | 98 | 554 | 478 | 674 | 3817 | 2490 |
| `企业定额_B册_通用安装.sqlite` | 通用安装 | 14 | 136 | 1188 | 85 | 2294 | 12470 | 4098 |
| `企业定额_C册_市政园林.sqlite` | 市政园林 | 15 | 64 | 822 | 62 | 901 | 4687 | 1561 |
| `企业定额_D册_水运工程.sqlite` | 水运工程 | 10 | 22 | 409 | 0 | 531 | 3769 | 894 |

统一表名详见 `CLAUDE.md#企业定额-4-册统一-schema`。

## 术语库

- `glossary.sqlite` — 中英双向术语库，35,187 行。分类：`norm_name`(21,694)、`chapter_name`(4,304)、`nrm_item_name`(487)、`section_title`(38)、`enterprise_item_name`(2,877)、`division_name`(61)、`sub_division_name`(318)、`consumption_name`(5,408)。含 NRM 英标术语（已回填中文）+ 现有 `norm_Name_EN`/`chapter_EN` 提取的双语对 + 翻译新增的企业清单层与人材机名称对

## 行业/地方定额

- `北京2012_建设工程计价依据_预算定额.sqlite` — 北京 2012 预算定额（土建为主）
- `北京2012_房屋修缮工程计价依据_预算定额.sqlite` — 北京 2012 房修定额
- `北京2021房屋建筑与装饰工程预算消耗量定额.sqlite` — 北京 2021 定额
- `norms_jts276-1-2019_excel.sqlite` — JTS/T 276-1-2019 沿海港口水工建筑
- `norms_jts276-3-2019_excel.sqlite` — JTS/T 276-3-2019 沿海港口疏浚
- `JTS_T_276-1-2019_沿海港口水工建筑工程定额.sqlite` — 同上另一来源
- `JTST 271-2020 水运工程工程量清单计价规范.sqlite` — JTS/T 271-2020 清单计价

## 项目专用

- `三航局Laldia项目人工机械定额.sqlite` — Laldia 项目人工/机械消耗量
- `boq_pk_civil_202606.sqlite` — BOQ 土建清单匹配结果

## 主库

- `quota_data.sqlite` — 整合库（汇总多来源定额数据）

## 备份

`backup/{原文件名}.{YYYYMMDD_HHMMSS}.bak` — 每次结构性变更前自动落地
