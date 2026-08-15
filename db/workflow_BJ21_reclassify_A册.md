# A册 BJ21定额重分类工作流

## 0. 执行摘要

### 范围
- **目标**: 重分类A册中来源为"北京2021_预算消耗量标准"的1,963条定额
- **来源**: 北京2021房屋建筑与装饰工程预算消耗量标准（16章）
- **目标精度**: 叶子章节层级（如 A.01.01.001）
- **方法**: 四阶段混合拓扑——Opus设计 + Haiku并行森林 + Sonnet交叉校验 + Opus仲裁

### 与C册的关键差异
C册是跨专业重分类（建筑定额→市政册），核心逻辑是"工艺相似性"。
A册是同专业重分类（建筑定额→建筑装饰册），BJ21章节与A册division有自然映射关系，
但叶子章节层级需要语义理解，因为BJ21原章节结构与A册叶子章不是一一对应。

---

## 1. 拓扑图

```
Phase 0            Phase 1                  Phase 2          Phase 3
(Opus设计)        (Haiku森林)              (Sonnet校验)     (Opus仲裁)

┌──────────┐    ┌─ Agent 01 (B01, ~200条) ─┐
│  Opus    │    ├─ Agent 02 (B02, ~200条) ─┤
│ 框架设计  │───├─ Agent 03 (B03, ~200条) ─┤── Sonnet ── Opus ── DB
│+数据集   │    ├─ Agent 04 (B04, ~200条) ─┤   交叉校验    仲裁    写入
│+映射表   │    ├─ Agent 05 (B05, ~200条) ─┤
│+Prompt   │    ├─ ...                     ─┤
└──────────┘    └─ Agent 10 (B10, ~200条) ─┘
```

---

## 2. Phase 0: Opus 框架设计

### 2.1 数据集构建
数据来源:
- A册 DB (企业定额_A册_建筑装饰.sqlite): Norm表 + chapter表 + norm_source表
- BJ21参考库 (北京2021房屋建筑与装饰工程预算消耗量定额.sqlite): quota_items.work_content

联表提取每条BJ21定额的:
- norm_ID, norm_Code, norm_Name, norm_Units
- 当前A册分类: chap_code + chap_name
- BJ21源章节路径: source_chap_path
- BJ21源工程内容: quota_items.work_content + subitem_title
- BJ21源章节上下文: sections表标题

### 2.2 映射框架
Opus构建 BJ21 16章 → A册 division 的一对多映射表，
为每个BJ21源路径提供候选A册叶子章列表（10-50个），而非全量607章。

### 2.3 Prompt 模板
Opus设计标准化分类prompt，包含系统指令、映射约束、
候选叶子章列表、3-5个金标示例、输出JSON Schema。

---

## 3. Phase 1: Haiku 并行森林

### 3.1 分批策略
- 1963条按源章节聚合后切分，每批~200条
- 同源章节不跨批
- 预估10批

### 3.2 每批次Prompt
包含:
1. 映射约束: BJ21源章→A册候选division+叶子章列表
2. 待分类条目: 本批200条定额的完整上下文
3. 输出Schema: 每条输出JSON含proposed_chap_code + confidence + rationale

### 3.3 输出规范
```json
{
  "batch_id": "B01",
  "total": 200,
  "items": [
    {
      "norm_ID": 30000005,
      "proposed_chap_code": "01.02.001",
      "confidence": "high",
      "rationale": "源章节为挖一般土方，属基础土石方范畴"
    }
  ]
}
```

---

## 4. Phase 2: Sonnet 交叉校验

### 4.1 校验项目
1. chap_code有效性: 所有proposed_chap_code在Chapter表中存在
2. 覆盖检查: 1963条全部有结果
3. 同名不同division: 相同norm_Name被分到不同division
4. 跨批一致性: 同一源章节的条目在不同批次中的分类趋势一致性
5. 置信度分布: low-confidence占比是否在合理范围(<15%)

### 4.2 输出
- 冲突清单: 需要Opus仲裁的条目列表
- 校验报告: 各division分配量统计、异常检测

---

## 5. Phase 3: Opus 仲裁

### 5.1 审核范围
- 全部 low-confidence 条目（预估~200条）
- Sonnet标记的冲突条目
- 分配到"异常"division的条目

### 5.2 仲裁规则
- 工艺相似性优先于文本相似度
- 参考BJ12同类条目的分类模式（A册中BJ12来源条目作为"正确分类"参照）
- 对于跨division边界案例，给出最终判定

---

## 6. 数据库更新

### 6.1 更新前备份
```bash
copy 企业定额_A册_建筑装饰.sqlite backup\企业定额_A册_建筑装饰.pre-bj21-reclass-{timestamp}.bak
```

### 6.2 审计表
```sql
CREATE TABLE IF NOT EXISTS bj21_reclass_audit (
    audit_ID INTEGER PRIMARY KEY AUTOINCREMENT,
    norm_ID INTEGER,
    old_chap_code TEXT,
    new_chap_code TEXT,
    confidence TEXT,
    rationale TEXT,
    batch_id TEXT,
    reclassified_at TEXT DEFAULT (datetime('now'))
);
```

### 6.3 更新SQL
```sql
UPDATE Norm SET chap_ID = (SELECT chap_ID FROM chapter WHERE chap_code = ?), 
               chap_Code = ?
WHERE norm_ID = ?;
```

---

## 7. 验证指标

- 1963条全部分类完成，无遗漏
- proposed_chap_code 100% 存在于Chapter表
- low-confidence占比 < 15%
- 随机抽50条人工检查，准确率 > 90%
- A册各division的BJ21分配量合理（与BJ12分布模式一致）

---

## 8. 执行顺序

```
Step 1: 数据库备份
Step 2: 构建工作数据集JSON (Phase 0.1)
Step 3: Opus构建映射框架 + Prompt模板 (Phase 0.2)
Step 4: 试点2个批次 (B01~B02, ~400条) 验证Prompt有效性
Step 5: 根据试点调整Prompt/映射
Step 6: 全量10批Haiku并行执行 (Phase 1)
Step 7: Sonnet交叉校验 (Phase 2)
Step 8: Opus仲裁 (Phase 3)
Step 9: DB更新 + 审计
Step 10: 验证报告
```
