# C册 BJ21定额重分类工作流程

## 0. 执行摘要

### 范围
- **目标**: 重分类C册中来源为"北京2021_预算消耗量标准"的3,722条定额（房屋建筑与装饰来源）
- **排除**: 1,026条"园林绿化工程"来源定额（已正确分配至C.20/C.21/C.22，不做重分类）
- **批次**: 按源章节路径分组，约12个批次，每批200-650条

### 核心问题
BJ21定额来自《北京2021房屋建筑与装饰工程预算消耗量标准》（建筑专业），被导入到C册（市政园林专业）时，基于文本相似度匹配到C册章节，导致:
1. C.05管网工程吸收了2,589条（占69.6%），远超合理范围，其中包含大量混凝土工/模板工/钢筋工等非管网内容
2. C.04隧道工程、C.07生活垃圾处理、C.08路灯工程、C.11综合管廊均无BJ21定额分配
3. 部分条目因名称含"管"字被归到管网，实际是建筑施工内容

### 核心原则
**工艺相似性 > 专业对口**: 市政工程常引用建筑定额中的通用工艺。分类依据是"这条定额描述的工作在市政语境中属于哪个专业部"，而非"源定额来自哪个预算标准"。

---

## 1. 预准备

### 1.1 数据库备份
```bash
copy "E:\Code\Norms-AI\db\企业定额_C册_市政园林.sqlite" ^
     "E:\Code\Norms-AI\db\backup\企业定额_C册_市政园林.pre-bj21-reclass-{timestamp}.bak"
```

### 1.2 生成工作数据集
执行以下查询，导出为JSON供后续批次使用：

**A) 待重分类清单** (3,722条)
```sql
SELECT n.norm_ID, n.norm_Code, n.norm_Name, n.norm_Units, n.norm_Specialty,
       c.chap_ID as current_chap_ID, c.chap_code as current_chap_code,
       c.chap_Name as current_chap_name,
       ns.source_norm_code, ns.source_chap_name, ns.source_chap_path, ns.source_book
FROM Norm n
JOIN Chapter c ON n.chap_ID = c.chap_ID
JOIN norm_source ns ON n.norm_ID = ns.norm_ID
WHERE ns.source_lib LIKE '%2021%'
  AND ns.source_book NOT LIKE '%园%'
ORDER BY ns.source_book, ns.source_chap_path, n.norm_Code
```

**B) C册目标章节清单** (所有叶子章)
```sql
SELECT c.chap_ID, c.chap_code, c.chap_Name, c.chap_Index
FROM Chapter c
WHERE c.chap_ID IN (
    SELECT DISTINCT n.chap_ID FROM Norm n
    JOIN norm_source ns ON n.norm_ID = ns.norm_ID
    WHERE ns.source_lib LIKE '%2012%'  -- BJ12才是C册原生分类，作为参考
)
ORDER BY c.chap_code
```

**C) 各division现有BJ12分布统计** (作为"正确分类"的参考基准)
```sql
SELECT substr(c.chap_code,1,4) as div_code, d.name as div_name,
       COUNT(*) as bj12_cnt, COUNT(DISTINCT c.chap_ID) as chapter_cnt
FROM Norm n
JOIN Chapter c ON n.chap_ID = c.chap_ID
JOIN norm_source ns ON n.norm_ID = ns.norm_ID
LEFT JOIN division d ON substr(c.chap_code,1,4) = d.code
WHERE ns.source_lib LIKE '%2012%'
GROUP BY div_code
ORDER BY bj12_cnt DESC
```

### 1.3 建立源→目标映射参考表
生成以下"源章节→候选目标division"的初筛映射，作为Sonnet分类时的约束框架：

| BJ21源章节/主题 | 候选C册division | 映射逻辑 |
|---|---|---|
| 土石方工程 (BJ21 Ch1) | C.01土石方 | 直接对应 |
| 地基处理与边坡支护 (BJ21 Ch2) | C.01土石方, C.02道路 | 地基处理通用 |
| 桩基工程 (BJ21 Ch3) | C.03桥涵, C.06水处理, C.11管廊 | 桩基用于桥梁/水池/管廊基础 |
| 砌筑工程 (BJ21 Ch4) | C.03桥涵, C.06水处理, C.22园林 | 砌筑用于桥台/池壁/景墙 |
| 混凝土及钢筋混凝土 (BJ21 Ch5) | C.03桥涵, C.06水处理, C.11管廊 | 混凝土结构用于桥梁/水池/管廊 |
| 金属结构工程 (BJ21 Ch6) | C.03桥涵, C.06水处理, C.08路灯 | 钢结构用于桥梁/水处理设备/灯杆 |
| 木结构工程 (BJ21 Ch7) | C.22园林景观, C.21园路园桥 | 木结构用于园林建筑/园桥 |
| 门窗工程 (BJ21 Ch8) | C.22园林景观, C.06水处理 | 门窗用于园林建筑/厂房 |
| 屋面及防水工程 (BJ21 Ch9) | C.06水处理, C.33措施, C.22园林 | 防水用于水池/建筑屋面 |
| 保温隔热防腐 (BJ21 Ch10) | C.05管网, C.06水处理 | 管道保温/池体防腐 |
| 楼地面装饰 (BJ21 Ch11) | C.02道路, C.21园路, C.22园林 | 地面铺装用于道路/园路/广场 |
| 墙柱面装饰 (BJ21 Ch12) | C.22园林景观, C.06水处理 | 墙面装饰用于园林建筑/厂房 |
| 天棚工程 (BJ21 Ch13) | C.22园林景观 | 天棚用于园林建筑 |
| 油漆涂料 (BJ21 Ch14) | C.05管网(管道刷油), C.03桥涵(钢结构油漆) | 按被涂物类型分流 |
| 其他装饰 (BJ21 Ch15) | C.22园林景观, C.21园路园桥 | 装饰用于园林 |
| 措施项目 (BJ21 Ch16) | C.33措施项目 | 直接对应 |

---

## 2. 分批策略与执行方式

### 2.1 批次划分
按source_book + source_chap_path的第一级分组，分为约12个批次。每批200-650条。

**批次清单**（由脚本自动生成，以下为示意结构）:
- Batch 01: 第一~三部 > 土石方 (~250条)
- Batch 02: 第一~三部 > 地基处理 (~290条)
- Batch 03: 第三部 > 桩基 (~150条)
- Batch 04: 第三部 > 砌筑 (~210条)
- ... (依此类推)

### 2.2 Sonnet分类执行方式
每个批次:
1. 提供一个prompt，包含:
   - 本批次的约100-200条定额（norm_ID + norm_Name + norm_Units + source_chap_name + source_chap_path + 当前分类）
   - C册全部15个division的名称和描述
   - 每个division的叶子章节列表（chap_code + chap_Name），供Sonnet选目标章节
   - 源→目标映射参考表
2. Sonnet输出结构化JSON
3. 每批结果存入独立JSON文件，便于回滚和审计

### 2.3 批次大小控制
- 每批不超过200条（确保分类质量）
- 若源章节超过200条，按source_chap_path的二级分组拆分为子批次
- 最大批次: C.05现有2,589条将拆分为约15个子批次

---

## 3. Sonnet分类输出规范

### 3.1 输出JSON Schema
```json
{
  "batch_id": "B01",
  "batch_source": "第一~三部 > 第一章 土石方工程",
  "classified_at": "2026-08-05T...",
  "total": 200,
  "items": [
    {
      "norm_ID": 12345,
      "norm_Code": "1-1",
      "norm_Name": "人工挖一般土方",
      "current_chap_code": "05.01.001",
      "current_chap_name": "C.05.01.001 混凝土管",
      "proposed_chap_code": "01.01.001",
      "proposed_chap_name": "C.01.01.001 挖一般土方",
      "proposed_division": "C.01",
      "confidence": "high",
      "rationale": "土方开挖工作在市政语境中属于通用土石方工程，映射到C.01。当前在C.05管网属于明显错误。"
    }
  ]
}
```

### 3.2 字段说明
| 字段 | 必填 | 说明 |
|---|---|---|
| norm_ID | Y | 数据库主键 |
| proposed_chap_code | Y | 目标章节的chap_code（必须在Chapter表中存在） |
| proposed_chap_name | Y | 目标章节全名（用于人工校验） |
| proposed_division | Y | 目标专业部代码 (C.01-C.33) |
| confidence | Y | "high" / "medium" / "low" |
| rationale | Y | 分类理由，1-2句话说明工艺相似性依据 |
| reassign | N | true=需要改分类，false=当前分类正确无需改动 |

### 3.3 置信度标准
- **high**: source→target映射直接对应（如"挖土方"→C.01土石方），或定额名称与目标章节名称高度匹配
- **medium**: 需要根据工艺相似性推断（如"混凝土基础"→C.03桥涵 vs C.06水处理），有合理但非唯一选择
- **low**: 跨多个专业部都有可能（如"预埋铁件"可能在C.03/C.06/C.11），需要Arbiter介入

---

## 4. 质量把控多Agent流水线

### 4.1 总体架构
```
[Sonnet Batch分类] → [Sonnet 自校验] → [Opus 审核] → [DB写入]
```

### 4.2 Sonnet自校验 (每批内)
每批次分类完成后，Sonnet执行自校验:
1. **覆盖检查**: 本批200条全部有分类结果
2. **chap_code有效性**: 所有proposed_chap_code均存在于Chapter表
3. **一致性检查**: 相同或高度相似的norm_Name是否被分配到同一division
4. **冲突标记**: 如果同一批次中相同名称的定额被分到不同division，标记为需要审核

### 4.3 Opus审核 (每2-3批后)
Opus负责:
1. **抽样审核**: 从每批随机抽20条 + 全部low-confidence条目
2. **跨批次一致性**: 检查不同批次的同类条目是否分配一致
3. **边界案例裁决**: 对Sonnet标记的冲突和low-confidence条目给出最终判定
4. **整体偏差检测**: 检查各division的分配量是否合理（如C.05不应再是最大接收方）

### 4.4 人工确认清单
以下条目标记为需要人工最终确认:
- confidence="low"的所有条目
- Opus审核中标记为disputed的条目
- 分配到C.04(隧道)、C.07(垃圾处理)、C.08(路灯)等原本无BJ21定额的division的条目

---

## 5. 分类决策规则 (决策树)

### 5.1 预处理: 识别"正确分类"
如果当前chap_code属于合理的division（参考映射表），且定额名称与章节名称有明显语义关联，标记reassign=false，confidence=high。避免"为了改而改"。

### 5.2 一级分流: 按工艺类型关键词
```
定额名称包含:
├─ 土方/石方/开挖/回填/压实/平整 → C.01 土石方
├─ 路/面层/基层/沥青/人行道/缘石/道板 → C.02 道路
├─ 桥/梁/墩/台/涵/桩/支座/伸缩缝 → C.03 桥涵
├─ 管/井/阀/法兰/水表/消防栓/接口/闭水 → C.05 管网 (注意: 必须有"水/气/热/排水"上下文)
├─ 池/沉/曝气/污泥/格栅/滤/消毒/搅拌/堰 → C.06 水处理
├─ 路灯/灯具/电缆/配电/光源 → C.08 路灯
├─ 钢筋/钢绞线/预应力/焊接/绑扎 → C.09 钢筋
├─ 拆除/铣刨/破碎/切割/凿除 → C.10 拆除
├─ 管廊/综合管沟/共同沟 → C.11 综合管廊
├─ 绿化/苗木/栽植/移植/草坪/花卉/灌溉/土壤 → C.20 绿化
├─ 园路/园桥/驳岸/路牙/金刚墙/拱券 → C.21 园路园桥
├─ 假山/花架/亭/廊/凳/椅/喷泉/小品/景墙 → C.22 园林景观
├─ 模板/脚手架/降水/围堰/便道 → C.33 措施项目
└─ 其他/模糊 → 进入二级分流
```

### 5.3 二级分流: 按工艺相似性 + 上下文推断
当一级关键词分流不足以判定时（如"混凝土浇筑"可属于C.03/C.06/C.11）:

1. **看源章节路径**: 如果源章节明确指向某个市政专业领域（如在"排水管道"下的混凝土工→C.05管网，在"桥梁"下的→C.03桥涵）
2. **看单位**: m3→结构工程(C.03/C.06), m→管道/道路(C.02/C.05), m2→装饰/防水(C.22/C.06), t→钢筋/钢结构(C.09/C.03)
3. **看norm_Specialty字段**: 如果该字段有值，可能标注了原始专业归属
4. **参考BJ12同类条目的分布**: 查询C册中BJ12来源的同类条目放在哪个division

### 5.4 关键边界案例处理
| 条目特征 | 可能的分类 | 判定依据 |
|---|---|---|
| "混凝土管/预应力管" | C.05管网 vs C.03桥涵 | 管道安装→C.05; 管桩→C.03 (看单位:m→C.05, m3→C.03) |
| "钢筋制安" | C.09钢筋 vs C.03桥涵 | 独立钢筋工程→C.09; 桥梁结构中钢筋→C.03 |
| "模板" | C.33措施 vs C.03/C.06 | 通用模板→C.33; 桥梁/水池专用模板→C.03/C.06 |
| "防水" | C.06水处理 vs C.33措施 | 池体防水→C.06; 屋面防水→C.33 |
| "钢结构" | C.03桥涵 vs C.08路灯 | 桥梁钢结构→C.03; 灯杆→C.08 |
| "砌筑" | C.03桥涵 vs C.06水处理 vs C.22景观 | 桥台→C.03; 池壁→C.06; 景墙→C.22 |

### 5.5 reclassify字段的特殊规则
- 如果proposed_chap_code与current_chap_code在同一division下（前4位相同），仅reassign=false（微调章节位置，不算重分类）
- 如果proposed_chap_code与current_chap_code完全相同，reassign=false, confidence=high
- 如果current分类明显正确（符合映射表+语义匹配），reassign=false

---

## 6. 数据库更新流程

### 6.1 更新前校验
```sql
-- 验证所有proposed_chap_code存在
SELECT DISTINCT proposed_chap_code FROM json_results
WHERE proposed_chap_code NOT IN (SELECT chap_code FROM Chapter)
-- 应返回0行

-- 验证无重复norm_ID
SELECT norm_ID, COUNT(*) FROM json_results GROUP BY norm_ID HAVING COUNT(*) > 1
-- 应返回0行

-- 验证总数
SELECT COUNT(*) FROM json_results WHERE confidence IN ('high','medium')
-- 应等于被处理的building-source BJ21总数
```

### 6.2 分批更新
对每条high + medium置信度的结果:
```sql
UPDATE Norm SET chap_ID = (SELECT chap_ID FROM Chapter WHERE chap_code = ?), 
               chap_Code = ?
WHERE norm_ID = ?;
```

### 6.3 审计日志
创建重分类审计表（如不存在则建表）:
```sql
CREATE TABLE IF NOT EXISTS reclass_audit (
    audit_ID INTEGER PRIMARY KEY AUTOINCREMENT,
    norm_ID INTEGER,
    old_chap_code TEXT,
    new_chap_code TEXT,
    confidence TEXT,
    rationale TEXT,
    batch_id TEXT,
    reclassified_at TEXT DEFAULT (datetime('now')),
    operator TEXT DEFAULT 'sonnet-opus-pipeline'
);
```

### 6.4 回滚方案
每批更新前保存该批次的"更新前状态"快照到reclass_audit，支持逐批回滚。

---

## 7. 事后验证

### 7.1 统计校验
1. 各division的BJ21总数与工作数据集一致（总和=3,722）
2. C.05的BJ21数量显著下降（从2,589下降到合理的管网相关条目数量，预估500-800条）
3. C.04/C.07/C.08/C.11等division有合理的BJ21分配
4. 无norm_ID丢失或重复

### 7.2 语义一致性抽查
随机抽取50条，人工检查分类是否合理。目标准确率 > 90%。

### 7.3 交叉验证
与A册（建筑装饰）中同名条目的classification对比。A册是建筑专业，C册是市政专业，同一工艺在不同册中的分类可能有差异，但应为合理差异而非错误。

---

## 8. 执行顺序

```
Step 0: 数据库备份 (1.1)
Step 1: 生成工作数据集JSON (1.2) 
Step 2: 确认批次划分方案 (2.1) - 由人工review后确认
Step 3: Batch 01-04 试点 (先跑4个小批次, 每批<200条)
Step 4: Opus审核试点批次 (4.3)
Step 5: 根据试点反馈调整分类规则 (5.1-5.4)
Step 6: 全量分批执行 (剩余批次)
Step 7: Opus抽查审核 + 边界裁决 (每2-3批后)
Step 8: 生成人工确认清单 (4.4)
Step 9: 人工确认low-confidence条目
Step 10: 数据库更新 (6.2)
Step 11: 事后验证 (7.1-7.3)
Step 12: 审计报告输出
```

### 避免破坏现有正确分类的措施
1. **reassign=false机制**: 只修改确实需要改的条目
2. **先试点后推广**: 4个试点批次验证规则后再批量执行
3. **逐批备份+审计**: 每批更新前保存旧状态，支持精准回滚
4. **园林绿化排除**: 1,026条园林绿化来源的条目完全不参与重分类
5. **BJ12条目不动**: 本次只处理norm_source表中source_lib='北京2021_预算消耗量标准'的条目

---

## 9. 附录

### A. Division代码对照表
| 代码 | 名称 | 说明 |
|---|---|---|
| C.01 | 土石方工程 | 土方开挖/回填/石方爆破、场平 |
| C.02 | 道路工程 | 路基/基层/面层/人行道/缘石/交通设施 |
| C.03 | 桥涵工程 | 桥梁/涵洞/立交/人行天桥、桩基/墩台/梁板/钢结构 |
| C.04 | 隧道工程 | 盾构/矿山法/明挖隧道 |
| C.05 | 管网工程 | 给排水管道/燃气管/热力管/管件/阀门/检查井 |
| C.06 | 水处理工程 | 给水厂/污水厂/泵站、水池/设备安装 |
| C.07 | 生活垃圾处理工程 | 填埋场/焚烧厂/中转站 |
| C.08 | 路灯工程 | 路灯/景观灯/电缆/配电 |
| C.09 | 钢筋工程 | 钢筋制安/预应力/钢筋连接 |
| C.10 | 拆除工程 | 结构拆除/路面铣刨/管线拆除 |
| C.11 | 城市地下综合管廊工程 | 管廊土建/管线支架/附属设施 |
| C.20 | 绿化工程 | 苗木栽植/移植/养护/灌溉 |
| C.21 | 园路园桥工程 | 园路铺装/园桥/驳岸/护栏 |
| C.22 | 园林景观工程 | 假山/花架/亭廊/喷泉/小品/景墙 |
| C.33 | 措施项目 | 模板/脚手架/降水/围堰/便道 |

### B. BJ21源数据库章节对照
BJ21源(16章): 1土石方 2地基处理 3桩基 4砌筑 5混凝土 6金属结构 7木结构 8门窗 9屋面防水 10保温防腐 11楼地面 12墙柱面 13天棚 14油漆 15其他装饰 16措施项目

### C. 工作产物清单
| 产物 | 位置 | 说明 |
|---|---|---|
| 工作数据集 | db/temp/bj21_work_dataset.json | 3,722条待分类条目 |
| 章节索引 | db/temp/c_chapter_index.json | C册全部叶子章 |
| 批次清单 | db/temp/batch_manifest.json | 批次划分方案 |
| 分类结果 | db/temp/bj21_reclass_results/ | 每批一个JSON |
| 人工确认清单 | db/temp/human_review_list.json | low-confidence条目 |
| 审计报告 | db/temp/reclass_audit_report.md | 最终统计和审计 |
