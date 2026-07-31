# 图片型PDF — 多Agent并行Markdown转换方案

> 父计划：`plan/实施计划_图片型PDF.md` 的 Step 3（AI逐节转换Markdown）
> 本方案解决 Step 3 的并行化，按"节"分派 agent 并行处理。

## 1. 问题分析

### 1.1 串行瓶颈

Step 3 是整个流程中最耗时的步骤：
- AI 读取一页 OCR JSON（1500-2000 行坐标数据）
- 逐块理解布局 → 映射列 → 纠错 OCR → 输出 Markdown
- 每页耗时 3-8 分钟（取决于布局复杂度）
- 大文档串行处理可达数十小时

### 1.2 并行可行性

页与页之间的依赖关系极弱：

| 依赖项 | 强度 | 处理方式 |
|:---|:---|:---|
| 续表链（continued_from） | 弱 | 仅需前一页的章节名/分项名/属性值，少量字符串 |
| 同节内页面 | 中等 | 共享表格结构（列数、费用项目列表），应同 agent 处理 |
| 跨节页面 | 无 | 完全独立，可并行 |

**结论：按"节"分派 agent，节内串行（2-8页），节间并行（可达 8 路同时）。**

## 2. 并行架构

### 2.1 整体流程

```
待处理页面
    │
    ▼
┌─────────────────────┐
│ 1. 预扫描            │  扫描所有剩余 OCR JSON
│    识别节边界         │  识别章节标题 + 页面类型
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ 2. 切分为节单元      │  将页面归组为独立的"节"
│    输出 section_index │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ 3. 生成 Agent Prompt │  每节一个自包含 prompt
│    含 OCR 数据+领域知识│  包含该定额的领域知识 + OCR JSON
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ 4. 并行调度          │  每批 5-8 个 agent (background)
│    分批→收集→验证    │  每批结束运行 verify_md.py
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ 5. 修复 + 收尾       │  重跑失败节，跨节边界检查
│                      │  定额编号连续性验证
└─────────────────────┘
```

### 2.2 分派单元：节（Section）

**节的定义**：从该节标题页开始，到下一节标题页之前（或该章结束）的所有连续定额表页面。

同一节内的页面共享：
- 相同的列数
- 相同的费用项目列表
- 相同的属性维度
- 相同的单位
- 页间有续表链

### 2.3 并行度

| 参数 | 参考值 | 说明 |
|:---|:---|:---|
| 每节平均页数 | 3-5 页 | 取决于定额结构 |
| 并行 agent 数 | 5-8 个 | 实测上限 |
| 单 agent 耗时 | 5-12 min | 取决于节内页数和复杂度 |
| 全量预估 | 2-4 小时 | 8路并行 × 多轮 |

## 3. 各步骤详解

### 3.1 预扫描

**脚本**: `scripts/prescan.py`

**输入**：待处理的 OCR JSON 文件列表

**输出**：`output/section_index.json`

```json
{
  "sections": [
    {
      "section_id": "s001",
      "chapter": "第X章 XXX",
      "section": "第X节 XXX",
      "subsection": "分项名称",
      "pages": [174, 175],
      "page_count": 2,
      "code_range": [2001, 2010],
      "num_columns": 9,
      "attributes": ["属性值1", "属性值2"],
      "unit": "每XX",
      "has_surcharge": false,
      "continued_from": null,
      "page_types": ["norms_table", "norms_table"]
    }
  ]
}
```

**识别逻辑**：
1. 扫描 OCR JSON 中的大字号文本（章节标题通常字号大、居中）
2. 匹配章节标题模式：`第X章`、`第X节`、`一、`、`二、`... `九、` 等
3. 检测定额编号列头（连续数字序列）推断列数
4. 检测属性标签推断维度
5. 检测"续前表"/"续表"标记建立页面链
6. 检测附注标记判断是否有运距附加费等特殊表

### 3.2 生成 Agent Prompt

**脚本**: `scripts/gen_agent_prompts.py`

为每节生成一个自包含的 Markdown 文件 `output/prompts/section_{id}.md`。

**Prompt 模板结构**：
```markdown
## 任务：将以下定额表OCR数据转换为Markdown

### 页面上下文
- 章节/节/分项/页码范围/定额编号范围
- 列数/属性维度/单位
- 是否有运距附加费

### 前页元数据（如本页是续前表）
{previous_meta}

### 关键领域知识
{该定额的领域知识：配对规律、消耗量规律、统一值/分组值项目清单、OCR常见错误修正表}

### OCR数据
{逐页粘贴OCR JSON内容}

### 输出要求
{Markdown格式规范，含表格规则}
```

**领域知识准备**：每种定额需要准备专属的领域知识，包括：
- **配对规律**：机械与工具的配对关系（如打桩船与锤型的配对）
- **消耗量规律**：材料消耗量的分组/循环模式
- **统一值/分组值项目**：哪些费用项目的值跨编码相同、哪些按属性分组
- **OCR错误修正表**：该定额常见的OCR误识别→正确文字映射
- **材料项数规律**：不同工况下的材料项目数量差异

> 领域知识应存放在 `references/` 目录下，按定额类型组织。`references/domain_knowledge_template.md` 可作为模板。

### 3.3 并行调度

**脚本**: `scripts/dispatch_agents.py`

**调度策略**：
```
将所有节按优先级排序：
  P0: 有 continued_from 依赖的节（需要等前节完成）
  P1: 独立节（新章节开头、无依赖）

每轮：
  1. 从队列取 5-8 个就绪的节
  2. 为每个节启动一个 background agent
  3. 等待全部完成或超时（15 min）
  4. 运行 verify_md.py 验证该批输出
  5. 标记完成的节，释放后续依赖节的阻塞
  6. 如有个别失败，重入队列
```

### 3.4 元数据提取

**脚本**: `scripts/extract_section_meta.py`

Agent 完成后，从最后一页 Markdown 提取元数据供下一节使用：

```python
# 从完成的MD frontmatter和最后几行提取
{
    "last_page": 175,
    "chapter": "第X章 XXX",
    "section": "第X节 XXX",
    "subsection": "分项名称",
    "last_code": 2284,
    "attributes": ["值1", "值2"],
    "unit": "每XX"
}
```

### 3.5 验证

**脚本**: `scripts/verify_md.py`

每批完成后的自动化验证：

| 验证项 | 方法 | 严重等级 |
|:---|:---|:---|
| 文件存在 | 检查 md 文件是否生成 | error |
| Frontmatter 完整性 | 检查 YAML 必填字段 | error |
| 定额编号数 | 每页编号数匹配预期 | error |
| 基价存在 | 每个定额编组有且仅有一行基价 | error |
| 数值格式 | 数量列可解析为数字或 `—` | error |
| 编号连续性 | 跨节边界无空隙/重叠 | warn |
| 基价合理性 | 在合理数值范围内 | warn |
| 行数范围 | 每页在合理行数范围内 | warn |

## 4. 风险与应对

| 风险 | 概率 | 影响 | 应对 |
|:---|:---|:---|:---|
| Agent OCR 数据过大超 context | 中 | 节内页面无法全部载入 | 大节（>6页）拆分为2个agent，前半输出元数据给后半 |
| 节边界识别错误 | 中 | 两个 agent 输出重叠或遗漏 | 预扫描 + 人工确认边界（约10分钟） |
| Agent 幻觉/编造数值 | 低 | 输出错误定额数据 | verify_md.py 多维度交叉验证 |
| Background agent 超时 | 低 | 该节需重跑 | 设置 15min 超时，失败自动重入队列 |
| 后续节依赖的前节未完成 | 中 | P1 节阻塞 | 预先生成所有 prompt，P0/P1 调度分离 |

## 5. 需要新建的文件

| 文件 | 用途 |
|:---|:---|
| `scripts/prescan.py` | 扫描 OCR JSON，识别节边界，输出 section_index.json |
| `scripts/gen_agent_prompts.py` | 为每节生成自包含 agent prompt |
| `scripts/dispatch_agents.py` | 分批调度 agent，跟踪进度 |
| `scripts/extract_section_meta.py` | 从 markdown 提取节元数据 |
| `scripts/verify_md.py` | 验证 markdown 完整性 |
| `output/section_index.json` | 节索引（由 prescan.py 生成） |
| `output/prompts/` | 存放各节的 agent prompt 文件 |
| `references/domain_knowledge_template.md` | 领域知识准备模板 |

## 6. 实施步骤

| 步骤 | 动作 | 预估时间 | 产出 |
|:---|:---|---:|:---|
| 1 | 编写 `prescan.py` 并运行 | 30 min | `section_index.json` |
| 2 | 准备领域知识（针对具体定额） | 30-60 min | `references/` 下的知识文件 |
| 3 | 人工确认节边界 | 10 min | 确认后的节列表 |
| 4 | 编写 `gen_agent_prompts.py` 并运行 | 20 min | 所有节的 prompt 文件 |
| 5 | 编写 `dispatch_agents.py` | 30 min | 调度脚本 |
| 6 | 编写 `verify_md.py` | 20 min | 验证脚本 |
| 7 | 编写 `extract_section_meta.py` | 15 min | 元数据提取脚本 |
| 8 | 并行 agent 分批执行 | 2-3 h | 全部 md |
| 9 | 最终跨节验证 | 15 min | 连续性确认 |

## 7. 新增文件清单

```
plan/
├── 实施计划_图片型PDF.md            ← 父计划
└── 多Agent并行方案_图片型PDF.md      ← 本方案
scripts/
├── prescan.py                       ← Step 1: 预扫描
├── gen_agent_prompts.py             ← Step 2: 生成 agent prompts
├── dispatch_agents.py               ← Step 3: 并行调度
├── extract_section_meta.py          ← Step 4: 元数据提取
├── verify_md.py                     ← Step 5: 验证
└── load_md_to_sqlite.py             ← 父计划 Step 4: SQLite入库
references/
└── domain_knowledge_template.md     ← 领域知识准备模板
output/
├── section_index.json               ← 节索引
└── prompts/                         ← agent prompt 文件
```
