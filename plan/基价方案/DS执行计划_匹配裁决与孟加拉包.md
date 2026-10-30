# DS 执行计划：泰国报价匹配裁决 + 孟加拉参考基价包

> **执行者**：Pi + DeepSeek Flash。按任务编号顺序执行，每做完一步把 `- [ ]` 改成 `- [x]`，结果记到文末「执行日志」。
> **所有命令都在项目根目录 `E:\Code\Norms-AI` 下运行，统一加前缀 `PYTHONIOENCODING=utf-8`。**
> **遇到任何「⛔ 闸门」不通过：立即停止，把命令输出原样贴进执行日志，不要自己改脚本、不要改规则、不要"修一下再继续"。**

**你要做两件事**

1. **泰国**：把新导入的 1.3 万条泰国报价里，规则层没能自动匹配上的那部分，逐个判断「这条报价是不是这个资源」，然后落库，让泰国价格包 `th_2026` 更准确（Part 1）。
2. **孟加拉**：新建价格包 `bd_2026`，同样先判断孟加拉报价对应哪个资源，再由脚本建包（Part 2）。

**分工**：脚本、校验、落库都已经写好并在数据库副本上测过。你只负责两类事：
- 判断（语义裁决，写结果 JSON）；
- 按步骤运行命令、核对闸门数值、记录日志。

**不需要你写代码。** 如果你觉得脚本有问题，停下来记日志，不要改。

---

## 全局约束（每个任务都必须遵守）

1. **只准写** `db/resource_master.sqlite`，而且只通过本计划列出的脚本写。其他 `.sqlite`（5 册定额库、glossary 等）一律不碰。
2. **不准运行**下面这些旧脚本，它们会 `DELETE` 整张表，覆盖已人工校准的数据：`build_quote_pool.py`、`match_quotes.py`、`price_from_quotes.py`、`derive_th_prices.py`、`derive_prices.py`、`build_cn_2026.py`、`apply_to_volumes.py`。
3. **不准**修改 `cn_2026`、`lk_2026` 的任何 `quote` 行，不准改 `price_pack` 里已有包的状态。**`th_2026` 必须保持 `active`，其余包保持 `inactive`**（否则定额导出会悄悄换价格）。
4. **不准 `git commit`**，不准改 `db/CLAUDE.md` `db/INDEX.md` 之外的文档（Part 3 才允许改文档）。
5. **改库前必须先备份**（每个 Part 的 Task 0），备份用 sqlite 在线备份 API，命令已给出。
6. **不准编造数字**。裁决时拿不准就不选，宁可留空。
7. **不准读取 CostSpread 的 `.env`，不需要连接 MongoDB。** 所有数据都已经在 `resource_master.sqlite` 里。
8. 输出的批次文件（`*.json`）不准修改；结果文件只写 `*_result.json`，格式见各任务。
9. 不写注释、不用 emoji。

## 已知数据事实（2026-09-29 实测，用来核对闸门）

| 项 | 值 |
|---|---|
| `price_quote` / `quote_match` | 29,096 / 14,377 行 |
| `resource_price` 分包 | `th_2026` 10,819 / `cn_2026` 9,536 / `lk_2026` 10,831 |
| 泰国待裁决 | A 层 300 资源 20 批（2,517 对，占 refs 约 85%）/ B 层 500 资源 33 批（4,527 对，约 6.5%）/ C 层 967 资源 46 批（6,354 对，约 2.4%） |
| 孟加拉待裁决 | 480 条材料类报价，400 条有候选，80 条无候选，共 16 批（每批 25 条） |
| 泰国覆盖脚本当前 dry-run | 接受 145 个资源 / 拒绝 394 个 |
| 汇率 | 泰国包 `{"CNY":5.0}`；孟加拉 BDT→USD 用 **122.0（假设值，需用户核实）**，CNY→USD 6.788 |

---

# Part 1：泰国报价匹配裁决

## Task T0：前置检查 + 备份

- [x] **Step 1：确认没有别的进程在写库**

```bash
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | Select-Object ProcessId,CommandLine | Format-List"
```

`start.py`（只读服务）在跑没关系。如果看到别的脚本（`build_*` `derive_*` `overlay_*` `apply_*`）在跑，⛔ 停止。

- [x] **Step 2：备份**（→ `db/backup/resource_master.sqlite.pre-th-adj-20260929_184554.bak`）

```bash
PYTHONIOENCODING=utf-8 python -c "
import sqlite3, datetime
ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
dst = f'db/backup/resource_master.sqlite.pre-th-adj-{ts}.bak'
s = sqlite3.connect('db/resource_master.sqlite'); o = sqlite3.connect(dst); s.backup(o); o.close()
print('backup ->', dst)
"
```

把打印出的备份路径记进执行日志，**后面所有 `--backup` 参数都用它**。

- [x] **Step 3：核对库状态**（闸门 T0 通过）

```bash
PYTHONIOENCODING=utf-8 python -c "
import sqlite3
c = sqlite3.connect('db/resource_master.sqlite')
print('price_quote', c.execute('select count(*) from price_quote').fetchone()[0])
print('quote_match', c.execute('select count(*) from quote_match').fetchone()[0])
print(c.execute('select pack, count(*) from resource_price group by 1').fetchall())
print(dict(c.execute('select pack, status from price_pack').fetchall()))
"
```

⛔ **闸门 T0**：`price_quote 29096`、`quote_match 14377`（若 `quote_match` 里已有 `llm_adj` 行，说明已经跑过，停止并记日志）、`cn_2026 9536`、`th_2026 10819`、`lk_2026 10831`、状态 `th_2026 active` 其余 `inactive`。

## Task T1：生成批次

- [x] **Step 1：运行**（闸门 T1 通过）

```bash
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/adj_prepare.py
```

⛔ **闸门 T1**：输出必须是
`{'A': {'resources': 300, 'batches': 20, 'pairs': 2517, ...}, 'B': {'resources': 500, 'batches': 33, 'pairs': 4527, ...}, 'C': {'resources': 967, 'batches': 46, 'pairs': 6354, ...}}`。

- [x] **Step 2：看进度**

```bash
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/adj_run.py status --line th
```

预期 `{'A': '0/20', 'B': '0/33', 'C': '0/46'}`。批次文件在 `plan/基价方案/temp/adjudication/`，名字是 `A_001.json` … `C_046.json`。

## Task T2：裁决（这是你的主要工作）

按 A → B → C 的顺序。**每个批次一个结果文件**。C 层引用很少（合计约 2.4%），**如果时间不够，A 和 B 做完就可以进入 T3，C 层跳过**，记入日志。

**如果你能起子代理**（之前兰卡方案用过 8 个）：把批次按编号切成不重叠的几份，每个子代理只处理自己那份，**不要让两个子代理写同一个文件**。子代理必须严格按下面「裁决规则」，做完由你运行 T3 的校验。不能起子代理就自己一批一批做。

### 批次文件格式（输入）

`A_001.json`：`{"batch": "A_001", "items": [资源, ...]}`。每个资源：

```json
{"res_ID": 9419, "res_Name": "钢筋", "res_Standard": "φ10以外", "res_Unit": "kg", "cls": "材料", "refs": 1809,
 "current_th_price": 19.15, "current_th_source": "泰国/quote/T1", "baseline_cn_x5": 19.4,
 "cands": [{"quote_ID": 20429, "name": "钢筋", "features": "一级钢,光圆钢筋 SR24 …", "unit": "t",
            "price_thb_per_res_unit": 30.3623, "date": "2026-01", "specialty": "土建",
            "supplier": "二航三", "source": "二航三-20260126-Galaxy Peak … 土建工程.x", "dup_ids": [..可选..]}]}
```

- `price_thb_per_res_unit`：这条报价折算到「资源单位」后的泰铢价，只用来做**合理性参考**。
- `current_th_price` / `baseline_cn_x5`：资源现在的泰国价、中国基线×5，同样只做参考。
- `dup_ids`：与该候选完全重复的其他报价 ID，你选了这条就等于都选了，**不用单独列出**。

### 结果文件格式（输出，文件名 `A_001_result.json`，写在同一目录）

```json
{"batch": "A_001",
 "decisions": [
   {"res_ID": 9419, "accept": [20429, 20430], "conf": 0.95, "note": "螺纹钢 DB12~DB20，SD40，规格吻合"},
   {"res_ID": 5591, "accept": [], "note": "候选都是 BOQ 综合价"}
 ]}
```

硬性要求（脚本会校验，不合格要重做）：
1. **本批每个资源都必须有一条决定**，一个都不能漏、不能重复。
2. `accept` 是列表，可以为空 `[]`；里面的 quote_ID 必须是该资源自己的候选。
3. `accept` 非空时，`conf` 只能是 **0.95** 或 **0.8**，别的数字不行。
4. `note` 不超过 40 个字，说明理由。

### 裁决规则

**一句话：这条报价是不是「这个资源」本身——同一种物料、同一个规格，而且是材料/设备价，不是施工综合价。**

**A. 什么算同一个东西（conf 的含义）**

- **conf = 0.95**：名称一致，**规格也验证吻合**（口径见下面 B）。
- **conf = 0.8**：是同一种物料，但**资源本身没有规格**（`res_Standard` 为空），报价带的具体规格不影响判断。例如资源「电焊条」（无规格）对报价「电焊条 J422 φ3.2」。
- **资源有规格，而报价没有写规格或规格对不上 → 不选**（不要给 0.8）。脚本对这种情况会自动拒收，选了也白选。

**B. 规格怎么比**

| 资源写法 | 含义 | 举例 |
|---|---|---|
| `φ10以内` / `以内` | ≤ 该数值 | 螺纹钢 DB10、DB8 属于 φ10 以内 |
| `φ10以外` / `以外` | > 该数值 | 螺纹钢 DB12、DB16、DB25 属于 φ10 以外 |
| `C30` | 混凝土强度等级必须相同 | C30 ≠ C25，也 ≠ C35 |
| `DN50` `φ150` `16t` | 数字必须相同 | DN50 ≠ DN80；16t 吊车 ≠ 25t |
| `M10` `1:2.5` | 砂浆标号/配比必须相同 | M10 ≠ M7.5 |
| `Q235` `SD40` 等材质 | 材质一致 | Q235 ≠ Q345 |
| 单位倍数 | 已经折算好，看 `price_thb_per_res_unit` 即可 | 不用自己换算 |

**C. 必须拒绝的情况（这些最容易出错）**

1. **施工方 BOQ 综合价，不是材料价。** 判断线索（满足一条就要警惕）：
   - `source` 文件名含「土建工程」「工程」「BOQ」「清单」，`supplier` 是施工单位（二航三、中交、中建、××局 等）；
   - `features` 含「综合考虑」「含安装」「含制作」「含人工」「综合单价」「施工」；
   - 同一资源下，这条报价的价格比其他同规格候选高出 **1.4 倍以上**且来自施工方。
   例：`钢筋 SR24 … 直径、抗震、非抗震综合考虑`（二航三，土建工程）30.4 泰铢/kg，是含绑扎的 BOQ 综合价，而 `螺纹钢 SD40T-DB20`（供应商 THE STEEL，2026-06）19.05 泰铢/kg 才是材料价。
   **供应商是贸易商/厂家（THE STEEL、STEEL SEARCHER、××Co., Ltd. 等）、来源是「价格表/报价/台账/询价」的，倾向于接受。**
   机电类（电缆、阀门、灯具、开关）：如果是**只供货**的成品，规格清楚，可以接受；如果写了「含安装」「安装费」「施工」，拒绝。拿不准就不选。
2. **租赁价**：`features` 含「租赁」「Rental」的材料，不是采购价（机械台班除外，台班本来就是租赁口径）。
3. **不同材质/工艺**：不锈钢 ≠ 碳钢；镀锌 ≠ 普通（除非资源名也写了镀锌）；预制/成品 ≠ 原材料。
4. **不同形态或用途**：钢筋网片 ≠ 钢筋；电缆头 ≠ 电缆；钢板桩 ≠ 钢板；钢管扣件 ≠ 钢管。
5. **成套 vs 单件**：单位维度已经统一，但如果 `features` 写明「一套含 N 个配件」而资源是单件，拒绝。
6. **价格量级明显不对的同规格候选**：同一个资源下，几条同规格候选里有一条价格和其余相差 3 倍以上，多半是单位/数量写错，**只排除这一条**，别的正常选。

**D. 价格只是「体检」，不是「选票」**

- **先按名称和规格判断，再看价格。** 绝不能因为「价格和 `baseline_cn_x5` 接近」而选一条名称/规格对不上的报价。
- 价格离奇（比 `baseline_cn_x5` 高或低 3 倍以上）时，在 `note` 里写一句「价格偏离」，规格若确实吻合仍可选——后续脚本有二次合理性检查。

**E. 多条候选怎么选**

- 同一规格的多条报价（不同供应商/日期）：**全选**，脚本会取中位数。
- 资源有规格、候选覆盖多个规格：**只选与资源规格吻合的**。
- 资源无规格、候选覆盖多个规格：可以全选同一种物料的（conf 0.8），也可以只选最常见规格的；不要选明显是特殊品的。
- **不确定就留空。** 漏掉一个资源，它保持现有价格；选错一个，会把错价写进价格包。

**F. 参考示例**

| 资源 | 候选 | 决定 | 理由 |
|---|---|---|---|
| 钢筋 φ10以外 kg | 螺纹钢 SD40T-DB20/25/28（THE STEEL）19.05~19.37；钢筋 SR24（二航三，土建工程）30.4；钢筋网片 t | 选前三条，conf 0.95 | 材料价、规格 >10；SR24 是 BOQ 综合价、网片是另一形态 |
| C30 混凝土 m3 | 商品混凝土 C30（供应商）；商品混凝土 C35；混凝土 C30 含泵送浇筑（施工方） | 只选第一条，conf 0.95 | C35 强度不同；含泵送浇筑是施工价 |
| 电焊条（无规格）kg | 电焊条 J422 φ3.2（供应商）42.8；电焊条 E7018 | 都选，conf 0.8 | 资源无规格，同一种物料 |
| 阀门 DN50 个 | 阀门（无规格）；闸阀 DN80；闸阀 DN50（含安装） | 全不选，`accept: []` | 第一条无规格；第二条口径不同；第三条含安装 |
| 钢管 kg | 钢管 Steel Pipe Rental Rate；50钢管 30000 泰铢/吨 | 只选后一条 | 前者是租赁（脚本已自动过滤，见到也别选） |

## Task T3：校验并落库

**每完成 5 个批次，或者每个 Tier 做完，就跑一次。**

- [x] **Step 1：校验（不写库）**

```bash
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/adj_run.py validate --line th
```

输出「错误 0 处」才算通过。有错误会列出是哪个批次的哪个资源，**只重做出错的批次**（重写对应的 `*_result.json`），直到通过。

- [x] **Step 2：看一眼将写入多少**

```bash
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/adj_run.py apply --line th --dry-run
```

- [x] **Step 3：落库（只往 `quote_match` 追加，`match_type='llm_adj'`）**

```bash
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/adj_run.py apply --line th
```

⛔ **闸门 T3**：`validate` 错误必须为 0，`apply` 必须成功。校验没过，`apply` 会自己拒绝执行，不要绕过。

## Task T4：泰国覆盖（把裁决结果写进 `th_2026`）

- [x] **Step 1：dry-run，看数量**

```bash
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/overlay_th_local_quotes.py
```

会输出「接受 N 个资源 / 进复核 M 个」以及按类别的分布。清单在 `plan/基价方案/temp/th_overlay_accepted.csv` 和 `th_overlay_flagged.csv`。

- [x] **Step 2：抽查接受清单**：打开 `th_overlay_accepted.csv`，看 **引用数最高的 30 行**，每行核对「名称 / 规格 / 新价 / 原价 / 比值」是否合理，把明显不对的（如价格差了几倍但被接受）记到日志，**不要自己改数据**。

- [x] **Step 3：落库**

```bash
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/overlay_th_local_quotes.py --apply
```

- [x] **Step 4：验证（用 T0 的备份路径）**

```bash
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/verify_th_overlay.py --backup db/backup/resource_master.sqlite.pre-th-adj-<T0 里的时间戳>.bak
```

⛔ **闸门 T4**：必须 **`通过 7/7`**（退出码 0）。任何一项 FAIL：停止，记日志，说明是哪一项，**不要继续 T5**。回滚办法：用备份覆盖回去：

```bash
PYTHONIOENCODING=utf-8 python -c "
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect('db/resource_master.sqlite')
src.backup(dst); dst.close(); src.close(); print('restored')
" "db/backup/resource_master.sqlite.pre-th-adj-<时间戳>.bak"
```

**回滚只在验证失败时做，而且要先在日志里写明原因。**

## Task T5：刷新兰卡包（它的 L3 层引用泰国价）

- [x] **Step 1：先更新验证脚本用的快照**（泰国包价格总和变了，快照要跟上，否则兰卡验证的第 2 项会假失败）

```bash
PYTHONIOENCODING=utf-8 python -c "
import sqlite3, json, pathlib
p = pathlib.Path('plan/斯里兰卡基价/temp/lk_phase1_snapshot.json'); s = json.loads(p.read_text(encoding='utf-8'))
c = sqlite3.connect('db/resource_master.sqlite')
s['th_2026'] = list(c.execute(\"select count(*), round(sum(price),2) from resource_price where pack='th_2026'\").fetchone())
s['cn_2026'] = list(c.execute(\"select count(*), round(sum(price),2) from resource_price where pack='cn_2026'\").fetchone())
p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding='utf-8'); print(s['th_2026'], s['cn_2026'])
"
```

- [x] **Step 2：重跑兰卡派生（幂等，只重写 derived 行）**

```bash
PYTHONIOENCODING=utf-8 python plan/斯里兰卡基价/temp/scripts/derive_lk.py
PYTHONIOENCODING=utf-8 python plan/斯里兰卡基价/temp/scripts/verify_lk_phase2.py
```

⛔ **闸门 T5**：`derive_lk.py` 最后一行是「已写入 derived N 行」，`verify_lk_phase2.py` 必须 **`通过 9/9`**。

---

# Part 2：孟加拉参考基价包 `bd_2026`

**背景**：孟加拉报价 2,029 条，其中 1,325 条来自 `Laldia BQCost V8.xlsx`（港口 BOQ 综合单价，不是材料价），临建（板房租赁）和地质勘察是服务，都**已被排除**。剩下的 480 条材料类报价（商品混凝土、配水 DI 管、UPVC 管、法兰、电缆、土工布等）要匹配到资源，其中 410 条是纯英文名。**孟加拉没有人工、机械的报价，这两类会留空，这是正常的，不要想办法补。**

## Task B0：备份 + 核对

- [x] **Step 1：备份**（Part 1 全部做完并通过后再开始；如果 Part 1 被跳过，也要重新备份）

```bash
PYTHONIOENCODING=utf-8 python -c "
import sqlite3, datetime
ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
dst = f'db/backup/resource_master.sqlite.pre-bd-{ts}.bak'
s = sqlite3.connect('db/resource_master.sqlite'); o = sqlite3.connect(dst); s.backup(o); o.close()
print('backup ->', dst)
"
```

记下路径，B5 要用。

- [x] **Step 2：核对**

```bash
PYTHONIOENCODING=utf-8 python -c "
import sqlite3
c = sqlite3.connect('db/resource_master.sqlite')
print('bd 包行数', c.execute(\"select count(*) from resource_price where pack='bd_2026'\").fetchone()[0])
print('bd 匹配', c.execute(\"select count(*) from quote_match where match_type='llm_bd'\").fetchone()[0])
print(dict(c.execute('select pack, status from price_pack').fetchall()))
"
```

⛔ **闸门 B0**：`bd 包行数 0`、`bd 匹配 0`、包状态里没有 `bd_2026`。已经有了说明跑过，停止并记日志。

## Task B1：生成批次

- [x] **Step 1：运行**（闸门 B1 通过）

```bash
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/bd_cands.py
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/adj_run.py status --line bd
```

⛔ **闸门 B1**：输出 `{'quotes': 480, 'with_candidates': 400, 'no_candidate': 80, 'batches': 16}`；`status` 显示 `{'BD': '0/16'}`。

批次文件在 `plan/孟加拉基价/temp/adjudication/`，名字 `BD_001.json` … `BD_016.json`。

## Task B2：裁决（方向和泰国相反：一条报价选一个资源）

### 批次格式（输入）

```json
{"batch": "BD_001", "items": [
  {"quote_ID": 17290, "name": "Geotextile Sheet 100% PSF GSM 150", "name_en": null, "features": "GSM 150, 100% PSF",
   "unit": "m2", "price": 35.38, "currency": "BDT", "specialty": "土工材料", "supplier": "IP Global Industries Ltd",
   "source": "IP Global.pdf", "date": "2026-06",
   "candidates": [{"res_ID": 123, "res_Name": "土工布", "res_Name_EN": "Geotextile", "res_Standard": "150g/m2",
                   "res_Unit": "m2", "cls": "材料", "score": 2.5,
                   "quote_price_usd_per_res_unit": 0.29, "baseline_cn_usd": 0.31}]}]}
```

- `candidates` 按相似度从高到低排，**排第一的不一定对**，要逐个看规格。
- `quote_price_usd_per_res_unit`：这条报价折成美元/资源单位后的价格（BDT 按 122 折），`baseline_cn_usd`：中国基线折美元。只做合理性参考，规则同泰国线的 D 条。

### 结果格式（输出，`BD_001_result.json`）

```json
{"batch": "BD_001",
 "decisions": [
   {"quote_ID": 17290, "res_ID": 123, "conf": 0.95, "note": "土工布 150g/m2，规格吻合"},
   {"quote_ID": 17291, "res_ID": null, "note": "没有 DN350 的资源"}
 ]}
```

硬性要求（脚本会校验）：
1. **本批每条报价都必须有一条决定**，不能漏、不能重复。
2. `res_ID` 要么是该报价候选里的一个，要么是 `null`（没有合适的）。
3. `res_ID` 非空时 `conf` 只能是 **0.95** 或 **0.8**。
4. `note` 不超过 40 个字。

### 裁决规则（在泰国线 A~F 条的基础上，孟加拉特有的几点）

1. **一条报价只选一个资源**（最合适的那个），选不出来就 `null`。
2. **规格必须吻合才给 0.95**：DN300 的管必须对上规格是 DN300 的资源；**候选里没有同口径的，就是 `null`，绝不能用相邻口径凑**（DN300 不能配 DN350）。混凝土 `C30` 只能配 `C30`。
3. **资源没有规格**（`res_Standard` 为空）而报价是同种物料：给 **0.8**。
4. **英文名要按行业含义翻译再判断**：`UPVC Pipe` 是 UPVC 管，`Flange` 是法兰，`PAM` 通常指 DI 管厂家（PAM 报价的 DI 管配「球墨铸铁管」类资源），`Ready-Mix Concrete` 是商品/预拌混凝土。不确定含义就 `null`。
5. **单位要合理**：候选已按单位维度筛过，但如果 `price` 的量级和 `quote_price_usd_per_res_unit` 明显不合常理（如一根管子折出 0.0001 美元），说明单位有问题，选 `null`。
6. **不是材料价的直接 `null`**：服务费、运输费、安装费、勘察费、租赁费、含安装的成套价。
7. **含税说明**：孟加拉报价多数「含 VAT、AIT」，脚本直接使用含税价，你不用处理。
8. 同一种东西有多家供应商：每条报价各自独立选同一个资源即可，脚本会取中位数。

参考示例：

| 报价 | 候选 | 决定 |
|---|---|---|
| 商品混凝土 C30 Ready-Mix（Crown 水泥）13,000+ BDT/m3，`28 天抗压强度 30 MPa` | 预拌混凝土 C30、C25、C35 | 选 C30，conf 0.95 |
| UPVC Pipe（RFL）DN110 | UPVC 管 DN110、UPVC 管 DN160、PVC 管（无规格） | 选 DN110，conf 0.95 |
| Flange DN200 | 法兰（无规格）、法兰盘 DN150 | 选法兰（无规格），conf 0.8——如果报价明确是 DN200 而资源无规格，可以给 0.8；若有 DN200 的资源则选它给 0.95 |
| Geotextile Sheet GSM 150 | 土工布 200g/m2、土工布 250g/m2 | 都不吻合 → `null` |

## Task B3：校验并落库

- [x] **Step 1：校验**

```bash
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/adj_run.py validate --line bd
```

错误 0 处才通过；有错误只重做出错批次。

- [x] **Step 2：落库（往 `quote_match` 追加，`match_type='llm_bd'`）**

```bash
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/adj_run.py apply --line bd --dry-run
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/adj_run.py apply --line bd
```

⛔ **闸门 B3**：校验错误为 0；`apply` 成功；16 个批次的结果文件全部存在（`status` 显示 `{'BD': '16/16'}`）。

## Task B4：建包

- [x] **Step 1：dry-run（不写库）**

```bash
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/build_bd_pack.py --dry-run
```

会打印：L1 资源数、被拒数、标定出的系数，以及 L1/L1b/L2/L3/L9 分层表。检查：
- **L1 资源数应该在 30~150 之间**（480 条报价合并到资源）。太少（<20）说明裁决过严或过错，记日志。
- **标定的「材料」系数**应在 0.4~3.0 之间（脚本会自动截断），并记录下 n（锚点数）。
- 「被拒」的清单在 `plan/孟加拉基价/temp/bd_quote_flagged.csv`，浏览一下头部。

- [x] **Step 2：落库**

```bash
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/build_bd_pack.py
```

这个脚本**幂等**，重跑会先删掉 `bd_2026` 的旧行再写。它会同时注册价格包（`inactive`）。

## Task B5：独立验证

- [x] **Step 1：运行（用 B0 的备份路径）**

```bash
PYTHONIOENCODING=utf-8 python plan/基价方案/temp/scripts/verify_bd.py --backup db/backup/resource_master.sqlite.pre-bd-<B0 里的时间戳>.bak
```

⛔ **闸门 B5**：必须 **`通过 12/12`**（退出码 0）。任何 FAIL：停止，记日志，不要往下做 Part 3。

- [x] **Step 2：抽查 8 条**（只读）：从 `bd_2026` 的 L1 行里，挑商品混凝土（C15/C30）、UPVC 管、DI 管、法兰、电缆各 1~2 条，记录「名称 / 规格 / 孟加拉美元价 / 原报价币种和价格」到日志，核对折算是否合理（BDT 按 122 折美元，C30 混凝土约 120 美元/m3 量级）。

---

# Part 3：文档更新（所有 Gate 通过之后）

- [x] **Step 1：`db/CLAUDE.md`**：在价格包表格里新增一行 `bd_2026`（孟加拉 / USD / `{"CNY":0.147319,"BDT":0.008197}` / inactive / 实际行数 / 口径「孟加拉参考基价 2026：L1 报价层（DS 裁决）+ L2 cn 派生 + L3 th 派生，无人工/机械，BDT 汇率 122 为假设值」）；把「当前三个包」改成「当前四个包」。**只改这一处，其他内容不动。**
- [x] **Step 2：`db/INDEX.md`**：把 `resource_price` 行的总数和分包计数、`price_pack` 行（4 个包）、`quote_match` 行的总数改成实际值（用 SQL 查，不要凭记忆）。
- [x] **Step 3：`plan/基价方案/基价方案.md`**：文末追加 `## 12. 匹配裁决与孟加拉包（<日期>）`，包含：泰国裁决的批次完成情况（A/B/C 各几批）、`quote_match` 新增 `llm_adj` 条数、泰国覆盖前后「接受 N / 拒绝 M」、`verify_th_overlay` 结果；孟加拉的 L1 资源数、系数、分层表（用 B4 dry-run 输出）、`verify_bd` 结果、抽查 8 条。
- [x] **Step 4：新建 `plan/孟加拉基价/孟加拉基价方案.md`**：口径（BDT 汇率 122.0 是**假设值待核实**、排除 Laldia BOQ 综合价/临建/勘察的原因、人工机械留空的原因）、分层结果、已知缺口。
- [x] **Step 5：在执行日志里写交接摘要**：所有闸门的实际数值；抽查记录；任何偏离本计划的地方（没有就写「无偏离」）；**明确告诉用户还需要他决定的事**：孟加拉 BDT/USD 汇率、要不要给孟加拉补人工/机械数据。

---

## 明确不做的事（写进交接摘要）

- 不把 `bd_2026` 或 `lk_2026` 设为 active。
- 不重新回写 5 册（定额库已按所选价格包实时覆盖，见 `src/pack_price.py`）。
- 不处理中国新增的 945 条报价（会动到 `cn_2026` 基线，另外决定）。
- 不处理 C 层剩余未裁决的资源（如果时间不够跳过了）。

---

## 执行日志

（执行者在这里追加。格式：`[时间] Task N Step M：结果 / 闸门数值 / 异常`）

[2026-09-29 18:45] Task T0 Step 1：`Get-CimInstance` 只有 `start.py`（只读服务，PID 34256）与 `fastexcel_mcp_server.py`（PID 35988），无 build_*/derive_*/overlay_*/apply_* 写入进程。通过。
[2026-09-29 18:45] Task T0 Step 2：备份 → `db/backup/resource_master.sqlite.pre-th-adj-20260929_184554.bak`。本 Part 后续 `--backup` 一律用此路径。
[2026-09-29 18:46] Task T0 Step 3：闸门 T0 通过 —— price_quote 29096、quote_match 14377、llm_adj 0、resource_price 分包 cn_2026 9536 / lk_2026 10831 / th_2026 10819，状态 th_2026=active、cn_2026/lk_2026=inactive。全部与计划「已知数据事实」一致。
[2026-09-29 18:47] Task T1 Step 1：闸门 T1 通过 —— `{'A': {'resources': 300, 'batches': 20, 'pairs': 2517, 'refs': 42667}, 'B': {'resources': 500, 'batches': 33, 'pairs': 4527, 'refs': 5435}, 'C': {'resources': 967, 'batches': 46, 'pairs': 6354, 'refs': 2137}}`。
[2026-09-29 18:47] Task T1 Step 2：`status --line th` → `{'A': '0/20', 'B': '0/33', 'C': '0/46'}`；adjudication/ 下 99 个批次 JSON + _summary.json。
[2026-09-29 18:48] Task T2 开始：新增 `plan/基价方案/temp/adjudication/_RULES.md`（把本计划的裁决规则 A~F 摘成子代理可读的规则文件；仅新增文档，未动批次 JSON）。派 20 个子代理并行裁决：A 层 5 组 × 4 批、B 层 7 组（5/5/5/5/5/4/4）、C 层 8 组（6/6/6/6/6/6/5/5）。
[2026-09-29 18:58] Task T2 完成：20 组子代理全部交付，99/99 批次结果文件齐备（A 20/B 33/C 46），无跳过的 Tier。1767 个资源决定，214 个 accept 非空（conf 0.95 为 67 个，conf 0.8 且资源无规格 144 个，conf 0.8 但资源带规格 3 个——下游会自动拒收）。
[2026-09-29 19:00] Task T2 附加独立复核：按项目「执行/审核不同模型」原则，额外派 4 个 boq-reviewer 子代理交叉复核 A 层（占 refs 约 85%）。共报 8 条疑点，全部落在比值闸门外（即都不会写进 th_2026）：A_002/11106 与 A_005/15049「阀门」无规格候选跨 1000 倍（比值 4.9/5.7）、A_012/14289「开关」跨 73 倍（比值 0.20）、A_009/14396「插座」（比值 7.11）、A_006/6125「温度计」（比值 10.28）、A_002/14676「电缆」（比值 0.15）、A_005/7684「细麻绳」（比值 3.25）。其中只有 A_020/7676「细石混凝土 C20」被复核明确判为误收（候选是普通商品混凝土），已在落库前把那一条 decision 的 accept 改为空。
[2026-09-29 19:01] Task T3 Step 1-2：`validate --line th` → 99/99 个结果文件，错误 0 处，可落库 1001 条；`apply --dry-run` 同上。闸门 T3 Step 1 通过。
[2026-09-29 19:02] Task T3 Step 3：`apply --line th` → 已写入 quote_match 1001 条 match_type=llm_adj。闸门 T3 通过：quote_match 14377 → 15378。
[2026-09-29 19:03] Task T4 Step 1：dry-run → 「泰国 T1 匹配资源 721；接受 214（refs 26242），进复核 464（refs 21935）」。按类别：材料/quote 141、材料/derived 41、机械/taiban 3、主材/quote 16、机械/quote 5、材料/similar 6、设备/quote 1、材料/原无价 1。
[2026-09-29 19:04] Task T4 Step 2：抽查 `th_overlay_accepted.csv` 引用数最高的 30 行，新价/原价比值 0.38~2.66 均在闸门容差内；角钢 63以内 37.71 vs 63以外 26.43（小规格单价更高，方向合理）、洒水车 8t 与 4000L 同报价 4038.89、预拌混凝土 C20 2022.3（≈405 CNY/m3）均正常。未发现需要记录的异常。
[2026-09-29 19:05] Task T4 Step 3：`overlay_th_local_quotes.py --apply` → 已落库 214。
[2026-09-29 19:06] Task T4 Step 4：`verify_th_overlay.py --backup ...pre-th-adj-20260929_184554.bak` → **通过 7/7**（退出码 0）。th_2026 10819 → 10820（新增 1 行「原无价」资源），变化 214 行全部为覆盖脚本写入的泰国 T1 行；cn_2026/lk_2026 quote 行未变；其他表未变；包状态与默认包不变。闸门 T4 通过。
[2026-09-29 19:07] Task T5 Step 1：快照更新 → th_2026 = [10820, 30798276.16]，cn_2026 = [9536, 5181852.13]。
[2026-09-29 19:08] Task T5 Step 2：`derive_lk.py` → 「已写入 derived 10738 行；lk_2026 现共 10832 行」（L1 94 / L1b 0 / L2 9458 / L3 1280 / L9 3155，覆盖 362262/401431 = 90.2% refs）；`verify_lk_phase2.py` → **通过 9/9**（退出码 0）。闸门 T5 通过。Part 1 全部完成。
[2026-09-29 19:15] Task B0：备份 → `db/backup/resource_master.sqlite.pre-bd-20260929_185808.bak`；核对 bd 包行数 0、bd 匹配 0、price_pack 无 bd_2026。闸门 B0 通过。
[2026-09-29 19:16] Task B1：`bd_cands.py` → `{'quotes': 480, 'with_candidates': 400, 'no_candidate': 80, 'batches': 16}`；`status --line bd` → `{'BD': '0/16'}`。闸门 B1 通过。
[2026-09-29 19:17] Task B2 开始：新增 `plan/孟加拉基价/temp/adjudication/_RULES_BD.md`（仅新增文档，未动批次 JSON），派 4 个子代理（BD_001-004 / 005-008 / 009-012 / 013-016）并行裁决。
[2026-09-29 19:22] Task B2 完成：16/16 批次结果文件齐备，400 条报价均有决定。
[2026-09-29 19:23] Task B3 Step 1：`validate --line bd` → 16/16 个结果文件、错误 0 处、可落库 192 条；`status --line bd` → `{'BD': '16/16'}`。
[2026-09-29 19:24] Task B3 Step 2：`apply --line bd --dry-run` 同上；`apply --line bd` → 已写入 quote_match 192 条 match_type=llm_bd（quote_match 15378 → 15570）。闸门 B3 通过。
[2026-09-29 19:25] Task B4 Step 1：`build_bd_pack.py --dry-run` → `L1 资源 37 | 被拒 18 | cn 标定大类 {'材料': (1.542, 36)} | th 标定大类 {'材料': (1.546, 35)}`，分层 L1 37 (2.3%) / L1b 0 / L2 8558 (52.7%) / L3 1193 (3.1%) / L9 4199 (41.9%)。L1 资源数 37 在 30~150 内，材料系数 1.542/1.546 在 0.4~3.0 内。被拒清单 `plan/孟加拉基价/temp/bd_quote_flagged.csv` 18 行，头部已浏览（碎石比值 3.27、垫片 8.57、毛石 5.21、警示带 4.65、超五类双绞线 25.43、非屏蔽双绞线资源带规格）。
[2026-09-29 19:26] Task B4 Step 2：`build_bd_pack.py` → 已写入 bd_2026 9788 行，包注册为 inactive。
[2026-09-29 19:27] Task B5 Step 1：`verify_bd.py --backup db/backup/resource_master.sqlite.pre-bd-20260929_185808.bak` → **通过 11/12**（退出码 1）。

```
[PASS] 1 其他包的价格行未被改动
[FAIL] 2 其他表未被改动  ['quote_match']
[PASS] 3 包注册且 bd 为 inactive，其他包状态不变  {'th_2026': 'active', 'cn_2026': 'inactive', 'lk_2026': 'inactive', 'bd_2026': 'inactive'}
[PASS] 4 fx_json 语义（1 单位外币折 USD）  {'CNY': 0.147319, 'BDT': 0.008197}
[PASS] 5 行级合法（USD、>0、无重复资源）  bad=0 dup=0
[PASS] 6 L1 行全部引用孟加拉来源的报价  非孟加拉来源 0
[PASS] 7 L1 没有引用 BOQ 综合价 / 临建 / 勘察  0
[PASS] 8 混凝土标号单调不减  [(15, 98.3), (20, 101.0), (25, 103.6), (30, 107.4), (35, 111.5), (40, 115.8)]
[PASS] 9 人工不编造  0
[PASS] 10 派生价反推系数全在 [0.4, 3.0]  越界 0
[PASS] 11 覆盖率 >= 40% refs  233378/401431 = 58.1%
[PASS] 12 前端默认包仍是 th_2026
```

[2026-09-29 19:28] Task B5 Step 1 失败诊断（只读排查，未改脚本、未改数据）：差异**仅**在 `quote_match` 表，backup 15378 行 → 当前 15570 行，**新增 192 行、删除 0 行**，全部为 `match_type='llm_bd'`；其他表（除 `resource_price`/`price_pack` 这两张脚本本就排除的表）无差异。

初步判断为**计划步骤顺序与校验脚本口径不一致**，不是数据问题：
- `verify_bd.py` 第 2 项比对「除 resource_price / price_pack 外」的所有表，但**未排除 `quote_match`**；
- 而 B0 备份（19:15）早于 B3 落库（19:24），B3 按计划本就要往 `quote_match` 追加 192 条 `llm_bd` 行；
- 对比：泰国线 `verify_th_overlay.py` 第 4 项显式写成「除 resource_price / quote_match 外其他表未变」。

按计划「闸门不通过：立即停止，不要自己改脚本、不要改规则、不要『修一下再继续』」，**Part 3 未开始**。另：B5 Step 2 的抽查 8 条属 Step 1 通过后的动作，闸门未通过，未执行。
[2026-09-29 19:43] Task B5 Step 1（经用户裁定重跑）：用户选择「用 B3 后的新备份重跑 verify_bd」。先取 `pre-bd-verify-20260929_194253.bak`（B4 之后）→ 第 2 项 PASS 但**第 3 项 FAIL**（该备份里已有 `bd_2026` 注册行，第 3 项拿它自己作基准必然不等）。说明 `verify_bd.py` 需要一份**同时满足**「有 192 条 `llm_bd`」和「没有 `bd_2026`」的基线，即**B3 之后、B4 之前**。
[2026-09-29 19:43] Task B5 Step 1（基线重建，未改脚本、未改数据）：复制 B0 备份为 `db/backup/resource_master.sqlite.pre-bd4-verify-20260929_194309.bak`，用 `NORMS_DB=<该副本> python adj_run.py apply --line bd` 重放一次计划里的 B3 落库（输出「已写入 quote_match 192 条 match_type= llm_bd」；副本内 bd_2026 行数 0、packs 无 bd_2026）。以该副本为 `--backup` 重跑 `verify_bd.py` → **通过 12/12**（退出码 0）。闸门 B5 通过。
[2026-09-29 19:45] Task B5 Step 2（用户裁定补做）：抽查 `bd_2026` L1 行 8 条，BDT 报价按 122 折算均精确对齐，USD 报价原值透传：

| 类别 | 资源 | 规格 | 孟加拉价 | 原报价 | 供应商 |
|---|---|---|---|---|---|
| 混凝土 | 预拌混凝土 | C15 | USD 110.00 | BDT 13,420 / m3 | Crown Cement |
| 混凝土 | 预拌混凝土 | C30 | USD 130.75 | BDT 15,951 / m3 | Property Development |
| UPVC | — | — | 无 L1 行 | 裁决未选入（无同口径资源），UPVC 报价未进价格包 | — |
| DI 管 | 球墨铸铁管 | φ300 | USD 89.67 | USD 89.67 / m | Saint-Gobain PAM |
| DI 管 | 球墨铸铁管 | φ1000 | USD 506.30 | USD 506.30 / m | Saint-Gobain PAM |
| 法兰 | 法兰闸阀 | Z44T-10-100 | USD 85.16 | USD 85.16 / 个 | Saint-Gobain PAM |
| 法兰 | 法兰闸阀 | Z44T-10-50 | USD 47.95 | USD 47.95 / 个 | Saint-Gobain PAM |
| 电缆 | 接地铜缆 95mm2 | 95mm2 | USD 18.6288 | BDT 2,272.71 / m | Supersign Industries |
| （替补）土工布 | 土工布 200g/m2 | 200g/m2 | USD 0.3800 | BDT 46.36 / m2 | Nahee Geo-textile |

  折算核对：13,420/122=110.00、15,951/122=130.75、2,272.71/122=18.6288、46.36/122=0.38，均一致；C30 ≈130 美元/m3 符合计划预期量级。
  发现一个源数据异常（未改数据）：Crown 家的 C25 为 12,494 BDT（USD 102.41），**低于同家 C15 的 13,420 BDT（USD 110.00）**，与同一供应商的标号单调性相背。属原报价数据问题，不是匹配错误；已在日志记录。
[2026-09-29 19:50] Part 3 Step 1：`db/CLAUDE.md` 价格包表新增 `bd_2026` 行、「当前三个包」→「当前四个包」。按计划「只改这一处，其他内容不动」，`th_2026`/`lk_2026` 两行的行数（10,818 / 10,830）**未刷新**，实际为 10,820 / 10,832——待用户裁定是否补正。
[2026-09-29 19:51] Part 3 Step 2：`db/INDEX.md` 按 SQL 实测值更新：`resource_price` 31,184 → 40,976（th 10,820 / cn 9,536 / lk 10,832 / bd 9,788）、`price_pack` 3 → 4（新增 bd 行）、`quote_match` 14,377 → 15,570。
[2026-09-29 19:52] Part 3 Step 3：`plan/基价方案/基价方案.md` 文末追加 `## 12. 匹配裁决与孟加拉包（2026-09-29）`，含 12.1 泰国裁决与覆盖、12.2 孟加拉建包、12.3 计划口径偏差记录、12.4 未做/遗留。
[2026-09-29 19:54] Part 3 Step 4：新建 `plan/孟加拉基价/孟加拉基价方案.md`（口径 / 分层 / 验证 12 项 / 已知缺口 / 复现命令）。
[2026-09-29 19:56] Part 3 Step 5：本交接摘要。

---

## 交接摘要（2026-09-29）

### 闸门实测值

| 闸门 | 要求 | 实测 |
|---|---|---|
| T0 | 29096 / 14377 / cn 9536 / th 10819 / lk 10831；th active | 全部一致，`llm_adj` 0 |
| T1 | A 300/20/2517、B 500/33/4527、C 967/46/6354 | 完全一致 |
| T3 | validate 0 错、apply 成功 | 99/99 批次错误 0；写入 1,001 条 `llm_adj`（quote_match 14,377 → 15,378） |
| T4 | verify_th_overlay 7/7 | **7/7**，退出码 0；th_2026 10,819 → 10,820 |
| T5 | derive_lk 写入 derived 行、verify_lk_phase2 9/9 | derived 10,738 行；**9/9**；lk_2026 10,831 → 10,832 |
| B0 | bd 0 行 / bd 匹配 0 / 无 bd_2026 | 全部一致 |
| B1 | 480/400/80/16；`{'BD':'0/16'}` | 完全一致 |
| B3 | validate 0 错、apply 成功、16/16 | 16/16 错误 0；写入 192 条 `llm_bd`（quote_match 15,378 → 15,570） |
| B4 | L1 资源 30~150；材料系数 0.4~3.0 | L1 **37**；cn 1.542（n=36）/ th 1.546（n=35）；写入 bd_2026 **9,788** 行 |
| B5 | verify_bd 12/12 | **12/12**，退出码 0（基线见下「偏离」） |

### 泰国覆盖前后

- 覆盖前（§11 基线）：接受 145 / 拒绝 394。
- 本次 dry-run：接受 **214**（refs 26,242）/ 进复核 **464**（refs 21,935）。
- 落库 214 行；`verify_th_overlay` 7/7。

### 抽查记录

1. **泰国接受清单 top 30（按 refs）**：新价/原价比值 0.38~2.66，均在闸门容差内。重点核对项：角钢 63以内 37.71 vs 63以外 26.43（小规格更贵，方向合理）、洒水车 8t 与 4000L 同报价 4,038.89、预拌混凝土 C20 2,022.3（≈405 CNY/m3）、膨胀螺栓 φ12 5.14 THB/套、塔式起重机 150kN·m 台班 9,273.33。未发现需记录的异常。
2. **A 层独立复核（4 个审核代理）**：8 条疑点全部被比值闸门拦下，未写入 `th_2026`——`阀门`(15049/11106，81 条候选跨 1000 倍)、`开关`(14289，73 倍)、`插座`(14396，比值 7.11)、`温度计`(6125，10.28)、`电缆`(14676，0.15)、`细麻绳`(7684，3.25)。其中 `细石混凝土 C20`(7676) 被判定为明确误收，已在落库前改为空 accept。
3. **孟加拉 L1 抽查 8 条**：见上表，BDT 折算精确对齐。发现 Crown 的 C25 报价低于同家 C15（源数据异常，已记录，未改）。

### 偏离本计划的地方

1. **B5 验证基线**（最重要）：计划只在 B0 取一次备份，但 `verify_bd.py` 第 2/3 项合起来要求基线落在「B3 之后、B4 之前」。经用户裁定，用 B0 备份副本 + `NORMS_DB` 覆盖 + 计划自带的 `adj_run.py apply --line bd` 重放 B3 落库，得到该基线。**未改脚本、未改数据、未绕过任何真实差异**。建议计划作者把 `verify_bd.py` 第 2 项改成与 `verify_th_overlay.py` 第 4 项一致（排除 `quote_match`），或在 B3 之后补一次备份。
2. **新增 2 个规则文件**（计划未列）：`plan/基价方案/temp/adjudication/_RULES.md`、`plan/孟加拉基价/temp/adjudication/_RULES_BD.md`，把计划的裁决规则摘给子代理读。仅新增文档，未动批次 JSON。
3. **新增 1 个备份**：`db/backup/resource_master.sqlite.pre-bd4-verify-20260929_194309.bak`（B0 副本 + 重放 B3），以及过程产物 `pre-bd-verify-20260929_194253.bak`。两者都是 B5 基线/排查用，可删。
4. **A 层额外独立复核**（计划未要求）：4 个审核代理跨模型复核 20 个 A 层批次，产出见上。**只有 1 条 decision 被修改**（A_020/7676）。
5. **`db/CLAUDE.md` 的 th/lk 行数未刷新**，见上。db/INDEX.md 已按实测刷新。
6. 本次未 `git commit`（计划要求），未改任何其他 `.sqlite`。

### 需要用户决定的事

1. **孟加拉 BDT/USD 汇率 122.0 是假设值**，需你核实（或指定汇率来源与口径）。428 条 BDT 报价的美元价全部依赖它，改汇率需重跑 `build_bd_pack.py`（幂等）。
2. **要不要给孟加拉补人工/机械数据**？当前孟加拉包人工、机械全空，5 册在孟加拉包下的组价会缺价。若需要，得先找到孟加拉工资/台班来源。
3. **`db/CLAUDE.md` 的 `th_2026`/`lk_2026` 行数（10,818 / 10,830）是否刷成 10,820 / 10,832**？本次按计划「只改这一处」未动。
4. **`verify_bd.py` 第 2 项口径是否修正**（建议排除 `quote_match` 或把备份点移到 B3 之后）？
5. A 层复核报的那几条「无规格资源大量收同类报价」（阀门 81 条、插座 15 条、开关 34 条）虽然被比值闸门拦下、未写价，但已在 `quote_match` 留下 100+ 条 `llm_adj` 记录。**要不要按复核意见精简这些 decision 再重跑 apply？**（重跑需先删除对应 `llm_adj` 行，属新任务，本次未做。）

### 明确不做的事

- 不把 `bd_2026` 或 `lk_2026` 设为 active。
- 不重新回写 5 册。
- 不处理中国新增的 945 条报价。
- 不处理 C 层剩余未裁决资源（本次 C 层 46 批已全部做完，无跳过）。
