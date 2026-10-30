# 斯里兰卡参考基价 lk_2026 —— Phase 2 派生层执行计划

> **执行者**：Pi + DeepSeek Flash。按 Task 0 → Task 6 顺序逐步执行，每做完一步把 `- [ ]` 改成 `- [x]`。
> **遇到任何「⛔ 闸门」不通过：立即停止，把输出原样记到本文末尾「执行日志」，不要自己改规则、不要"修一下再继续"。**
> 所有命令都在项目根目录 `E:\Code\Norms-AI` 下运行，统一加 `PYTHONIOENCODING=utf-8`。

**目标**：今晚把 `lk_2026`（斯里兰卡参考基价）从 52 条报价价补到约 10,800 个资源，覆盖约 90% 的定额引用，口径和泰国包 `th_2026` 一样。

**做法**：拿 Phase 1 已落库的 52 条兰卡报价当锚点，和 `cn_2026`（中国 2026 基价）逐条比出兰卡/中国比值，标定出兰卡的大类系数和品类系数。然后按瀑布逐层派生，每个资源命中一层就停：
L1 兰卡报价（已有，不动）→ L1b 混凝土按标号线性外推 → L2 `cn_2026 × 兰卡系数 ÷ 6.788` → L3 `th_2026 ÷ 5.0 × 兰卡/泰国系数 ÷ 6.788` → 其余留空。

**技术栈**：Python 3 + sqlite3（标准库）+ pytest。不用 Excel、不连 MongoDB、不调 LLM。

**前置文档**（只读，用来理解背景）：
- `plan/斯里兰卡基价/斯里兰卡基价方案.md`：Phase 1 的口径和结果
- `plan/基价方案/基价方案.md`：泰国方案，本计划照搬它的瀑布思路
- `db/CLAUDE.md` 中的「价格包 `price_pack`」一节

---

## 全局约束（每个 Task 都必须遵守）

1. **只准写 `db/resource_master.sqlite` 里 `resource_price` 表中 `pack='lk_2026' AND price_kind='derived'` 的行**，以及 `price_pack` 里 `lk_2026` 那一行的 `note` 字段。别的表、别的包一律只读。
2. **不准动** `price_kind='quote'` 的 52 条兰卡报价，也不准动 `th_2026` / `cn_2026` 的任何行。
3. **不准写** `price_factor`、`price_anchor`、`review_queue`。这三张表没有 `pack` 列，写进去会污染泰国的数据。兰卡系数只存到 `temp/lk_factors.json`。
4. **不准回写** 5 册定额库的 `Consumption` / `Norm`。5 册里现在是泰国价。
5. **`lk_2026` 保持 `status='inactive'`**。设成 active 的话，定额导出会按字典序悄悄换成兰卡价，原因见方案 §5。
6. 币种和汇率写死：本位币 USD；`FX_CNY_PER_USD = 6.788`；`FX_THB_PER_CNY = 5.0`（泰国包自己的汇率）。
7. `price_date` 统一用 `2026-08-21`，也就是 `common_lk.PACK_CUTOFF`。
8. 新脚本都放在 `plan/斯里兰卡基价/temp/scripts/`，中间产物放在 `plan/斯里兰卡基价/temp/`。项目根目录下不准建任何文件。
9. **不做 git commit**（`temp/` 本来就被 gitignore；db 的提交由用户决定）。
10. 缺价就留空，写进 `lk_unpriced.csv`。**不准编造数字**，也不准为了提高覆盖率放宽任何阈值。
11. 代码不写注释，只有「为什么」不明显时才写一行；不用 emoji。

## 已知数据事实（写计划时实测，2026-09-29）

| 项 | 值 |
|---|---|
| 资源总数 / 定额引用总数 | 13,987 / 401,431 |
| `lk_2026` 现有 | 52 行，全部 `price_kind='quote'`，覆盖 51,232 refs |
| L2 可派生（有 cn_2026 且未报价） | **9,494** 个资源 / 294,421 refs |
| L3 可派生（无 cn_2026、有 th_2026、未报价） | **1,281** 个资源 / 16,546 refs |
| 预计合计 | 约 10,827 个资源 / 约 362,199 refs（**约 90.2%**） |
| 预计留空 | 约 3,160 个：主材约 1,086 / 设备约 1,013 / 机械约 227（艘班等）/ 材料约 840 |
| `cn_2026` 的混凝土基价 | C15 459.36、**C20 312.62（倒挂）**、C25 484、C30 501.6、C35 520.96、C40 540.96 CNY/m3 |
| `cn_2026` 的钢筋（无规格） | **0.725 CNY/kg（明显错误，正常应在 3.5~4 左右）**。兰卡已有报价，不受影响，只需在报告里如实写出 |

## 评审重点（这些情况单元测试覆盖不到，最容易出错）

1. **人工工种变体会重复计入**：技工的 6 个变体价格完全相同，都拿来标定会让中位数偏向技工。规则是只用 `res_Standard` 为空的 3 个通用档（普工/技工/高级技工）。由 Task 1 的测试负责。
2. **品类归错**：`category_of` 看到「砖」字就归到「砖瓦砌块」，所以瓷砖锚点会得出 2.2 倍的系数，一旦套到标准砖、砌块上就会高估 2 倍。规则是用 `CATEGORY_BLOCKLIST` 屏蔽这一类。由 Task 1 的测试负责。
3. **混凝土标号倒挂**：cn_2026 里 C20 比 C15 便宜，按系数乘出来的价格也会倒挂。规则是按标号线性外推（L1b）。由 Task 4 的 verify 检查 5 负责。
4. **比值离群**：φ50钢管扶手 23 倍、灰浆搅拌机 20 倍、钢筋 6.9 倍，都是规格不同或基线本身错了。规则是比值超出 [0.3, 4.0] 就剔除。由 Task 1 的测试负责，Task 2 的闸门核对具体数值。
5. **品类跨大类**：`category_of` 看到「电焊」就把材料「电焊条」归到机械-泵焊搅拌；看到装修材料锚点主导的材料系数 1.537，会把柴油/电/水高估约 2 倍。规则是 `lk_category` 做大类一致性检查，大宗品用 `MANUAL_CATEGORY` 专家定值。由 Task 1 的测试负责。
6. **重跑时重复插入**：派生脚本必须幂等，先删掉本包的 derived 行再插。由 Task 3 的闸门负责（跑两遍，行数不变）。

---

## Task 0：前置检查 + 备份 + 快照

**Files:**
- Create: `db/backup/resource_master.sqlite.pre-lk-phase2-<时间戳>.bak`
- Create: `plan/斯里兰卡基价/temp/lk_phase1_snapshot.json`

- [x] **Step 1：确认没有别的进程在写库**

```bash
tasklist | findstr /I "python pythonw"
```

如果 `start.py` 服务在跑，没关系（它只读）。如果有别的脚本在写 `resource_master.sqlite`，⛔ 停止。

- [x] **Step 2：用 sqlite 的在线备份 API 做本地备份**（和 Phase 1 的备份放一起）

```bash
PYTHONIOENCODING=utf-8 python -c "
import sqlite3, datetime
ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
dst = f'db/backup/resource_master.sqlite.pre-lk-phase2-{ts}.bak'
src = sqlite3.connect('db/resource_master.sqlite'); out = sqlite3.connect(dst)
src.backup(out); out.close(); src.close()
print('backup ->', dst)
"
```

预期输出：`backup -> db/backup/resource_master.sqlite.pre-lk-phase2-2026....bak`。把这个路径抄到执行日志里。

- [x] **Step 3：记录 Phase 1 快照**，后面 verify 要用

```bash
PYTHONIOENCODING=utf-8 python -c "
import sqlite3, json
c = sqlite3.connect('db/resource_master.sqlite')
q = lambda s: c.execute(s).fetchone()
snap = {
  'lk_quote': list(q(\"select count(*), round(sum(price),4) from resource_price where pack='lk_2026' and price_kind='quote'\")),
  'lk_other': q(\"select count(*) from resource_price where pack='lk_2026' and price_kind<>'quote'\")[0],
  'th_2026': list(q(\"select count(*), round(sum(price),2) from resource_price where pack='th_2026'\")),
  'cn_2026': list(q(\"select count(*), round(sum(price),2) from resource_price where pack='cn_2026'\")),
  'status': dict(c.execute('select pack, status from price_pack').fetchall()),
}
open('plan/斯里兰卡基价/temp/lk_phase1_snapshot.json','w',encoding='utf-8').write(json.dumps(snap, ensure_ascii=False, indent=2))
print(json.dumps(snap, ensure_ascii=False))
"
```

⛔ **闸门 0**：`lk_quote[0] == 52`、`lk_other == 0`、`th_2026[0] == 10818`、`cn_2026[0] == 9536`、`status` 为 `{"th_2026":"active","cn_2026":"inactive","lk_2026":"inactive"}`。任何一项对不上就停止，说明库已被别人改过。

---

## Task 1：纯函数模块 `lk_phase2_core.py`（先写测试）

**Files:**
- Create: `plan/斯里兰卡基价/temp/scripts/lk_phase2_core.py`
- Test: `plan/斯里兰卡基价/temp/scripts/test_lk_phase2_core.py`

**Interfaces（Produces，后面的 Task 依赖这些名字）：**
- 常量 `FX_CNY_PER_USD=6.788`、`FX_THB_PER_CNY=5.0`、`RATIO_LO=0.3`、`RATIO_HI=4.0`、`MIN_CAT_ANCHORS=3`、`FACTOR_MIN=0.4`、`FACTOR_MAX=3.0`、`CATEGORY_BLOCKLIST={"砖瓦砌块"}`、`CLASS_FALLBACK={"主材":"材料","设备":"材料"}`
- `to_cny(price: float, currency: str) -> float`：遇到未知币种抛 `ValueError`
- `cny_to_usd(cny: float) -> float`
- `clamp(f: float) -> float`
- `concrete_grade(name: str, cls: str) -> int | None`：只认 `cls=='材料'` 且名称整串是 `C` 加两位数字
- `lk_category(name: str, cls: str, base_category: str, scope: str) -> str`：混凝土标号统一归到 `"混凝土砂浆"`；`category_of` 给出的 scope 和资源大类不一致时（如「电焊条」被归到机械-泵焊搅拌），退回大类名；其余原样返回
- 常量 `MANUAL_CATEGORY`：专家定值，覆盖实证品类系数，n 记 0（钢材-钢筋 1.3、油料 1.0、能源水电 1.0、气体 1.0）
- `calibrate(anchors: list[dict], use_category: bool = True) -> dict`：anchor 的键为 `res_ID, name, cls, category, standard, lk_usd, base_cny`；返回 `{"class": {cls: (factor, n)}, "category": {cat: (factor, n)}, "kept": [...], "dropped": [...]}`，kept/dropped 里的元素是原 anchor 加上 `ratio`，dropped 另外带 `why`
- `pick_factor(factors: dict, cls: str, category: str) -> tuple | None`：返回 `(factor, n, level, key)`，其中 level 为 `"category"` 或 `"class"`；factors 里的值用 tuple 或 list 都可以（JSON 读回来是 list）
- `concrete_line(quoted: dict[int, float]) -> tuple[float, float] | None`：用最小二乘拟合出 `(slope, intercept)`，不足 2 个点时返回 None

- [x] **Step 1：写测试** `test_lk_phase2_core.py`

```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lk_phase2_core as K  # noqa: E402


def a(cls, lk, base, category=None, standard="", name="x"):
    return {"res_ID": 0, "name": name, "cls": cls, "category": category or cls,
            "standard": standard, "lk_usd": lk, "base_cny": base}


def test_to_cny():
    assert K.to_cny(10, "USD") == pytest.approx(67.88)
    assert K.to_cny(50, "THB") == pytest.approx(10)
    assert K.to_cny(3, "CNY") == 3
    with pytest.raises(ValueError):
        K.to_cny(1, "EUR")


def test_cny_to_usd_roundtrip():
    assert K.cny_to_usd(K.to_cny(12.5, "USD")) == pytest.approx(12.5)


def test_calibrate_drops_labor_variant_outlier_duplicate():
    anchors = [
        a("人工", 19.95, 168.0),
        a("人工", 19.95, 168.0, standard="木工"),
        a("材料", 1.0, 6.788),
        a("材料", 1.0, 6.788),
        a("材料", 10.0, 6.788),
        a("材料", 2.0, 6.788),
        a("材料", 1.0, 0),
    ]
    res = K.calibrate(anchors)
    whys = sorted(d["why"] for d in res["dropped"])
    assert whys == sorted(["人工工种变体，不参与标定", "重复锚点", "比值越界", "基线价缺失"])
    assert res["class"]["材料"] == (pytest.approx(1.5), 2)
    assert res["class"]["人工"][0] == pytest.approx(19.95 * 6.788 / 168.0)


def test_category_needs_three_and_respects_blocklist():
    anchors = [a("材料", r, 6.788, category="混凝土砂浆") for r in (1.3, 1.33, 1.37)]
    anchors += [a("材料", r, 6.788, category="砖瓦砌块") for r in (2.0, 2.2, 2.5)]
    anchors += [a("机械", r, 6.788, category="机械-土方") for r in (0.8, 0.9)]
    res = K.calibrate(anchors)
    assert res["category"]["混凝土砂浆"] == (pytest.approx(1.33), 3)
    assert "砖瓦砌块" not in res["category"]
    assert "机械-土方" not in res["category"]


def test_calibrate_without_category():
    anchors = [a("材料", r, 6.788, category="混凝土砂浆") for r in (1.3, 1.33, 1.37)]
    assert K.calibrate(anchors, use_category=False)["category"] == {}
    assert "混凝土砂浆" in K.calibrate(anchors)["category"]


def test_factor_is_clamped():
    anchors = [a("材料", r, 6.788) for r in (3.5, 3.6, 3.9)]
    assert K.calibrate(anchors)["class"]["材料"][0] == K.FACTOR_MAX
    assert K.clamp(0.1) == K.FACTOR_MIN


def test_pick_factor_fallbacks():
    f = {"class": {"材料": [1.5, 16], "机械": [0.9, 11]},
         "category": {"混凝土砂浆": [1.33, 4]}}
    assert K.pick_factor(f, "材料", "混凝土砂浆") == (1.33, 4, "category", "混凝土砂浆")
    assert K.pick_factor(f, "主材", "主材") == (1.5, 16, "class", "材料")
    assert K.pick_factor(f, "机械", "机械-起重") == (0.9, 11, "class", "机械")
    assert K.pick_factor(f, "人工", "人工") is None


def test_concrete_grade_and_category():
    assert K.concrete_grade("C25", "材料") == 25
    assert K.concrete_grade(" C40 ", "材料") == 40
    assert K.concrete_grade("C25", "机械") is None
    assert K.concrete_grade("C25混凝土", "材料") is None
    assert K.lk_category("C30", "材料", "材料", "材料") == "混凝土砂浆"
    assert K.lk_category("水泥", "材料", "水泥", "材料") == "水泥"
    assert K.lk_category("电焊条", "材料", "机械-泵焊搅拌", "机械") == "材料"


def test_manual_category_overrides():
    anchors = [a("材料", r, 6.788, category="油料") for r in (2.0, 2.1, 2.2)]
    res = K.calibrate(anchors)
    assert res["category"]["油料"] == (1.0, 0)
    assert res["category"]["钢材-钢筋"] == (1.3, 0)
    assert "油料" not in K.calibrate(anchors, use_category=False)["category"]


def test_concrete_line():
    slope, b = K.concrete_line({25: 93.62, 30: 99.36, 35: 105.09})
    assert slope * 20 + b == pytest.approx(87.89, abs=0.01)
    assert slope * 40 + b == pytest.approx(110.83, abs=0.01)
    assert K.concrete_line({25: 93.62}) is None
```

- [x] **Step 2：跑测试，确认失败**

```bash
PYTHONIOENCODING=utf-8 python -m pytest plan/斯里兰卡基价/temp/scripts/test_lk_phase2_core.py -q
```

预期：`ModuleNotFoundError: No module named 'lk_phase2_core'`。

- [x] **Step 3：写实现** `lk_phase2_core.py`

```python
# -*- coding: utf-8 -*-
"""lk_2026 Phase 2 纯函数：币种换算、锚点标定、系数选取、混凝土标号外推。不碰数据库。"""
import re
import statistics

FX_CNY_PER_USD = 6.788
FX_THB_PER_CNY = 5.0
RATIO_LO, RATIO_HI = 0.3, 4.0
MIN_CAT_ANCHORS = 3
FACTOR_MIN, FACTOR_MAX = 0.4, 3.0
# category_of 按「砖」字把瓷砖/踢脚归进砖瓦砌块，其锚点套到标准砖/砌块上会高估约 2 倍
CATEGORY_BLOCKLIST = {"砖瓦砌块"}
CLASS_FALLBACK = {"主材": "材料", "设备": "材料"}
CONCRETE_RE = re.compile(r"^C(\d{2})$")
# 专家定值，覆盖实证品类系数（n 记 0）。材料大类系数由装修材料锚点主导，直接套大宗品会高估约 2 倍
MANUAL_CATEGORY = {
    "钢材-钢筋": (1.3, "兰卡钢筋报价 0.7356USD/kg≈4.99CNY 对 cn_2026 钢筋 φ10以内/以外 3.77/3.88；cn 无规格钢筋 0.725 为错值"),
    "油料": (1.0, "无兰卡锚点，国际大宗品按平价 1.0，待询价"),
    "能源水电": (1.0, "无兰卡锚点，按平价 1.0，待询价"),
    "气体": (1.0, "无兰卡锚点，按平价 1.0，待询价"),
}


def to_cny(price, currency):
    if currency == "CNY":
        return price
    if currency == "THB":
        return price / FX_THB_PER_CNY
    if currency == "USD":
        return price * FX_CNY_PER_USD
    raise ValueError(f"未知币种 {currency}")


def cny_to_usd(cny):
    return cny / FX_CNY_PER_USD


def clamp(f):
    return max(FACTOR_MIN, min(FACTOR_MAX, f))


def concrete_grade(name, cls):
    if cls != "材料":
        return None
    m = CONCRETE_RE.match((name or "").strip())
    return int(m.group(1)) if m else None


def lk_category(name, cls, base_category, scope):
    if concrete_grade(name, cls) is not None:
        return "混凝土砂浆"
    return base_category if scope == cls else cls


def calibrate(anchors, use_category=True):
    kept, dropped, seen = [], [], set()
    for x in anchors:
        if x["cls"] == "人工" and x["standard"]:
            dropped.append({**x, "ratio": None, "why": "人工工种变体，不参与标定"})
            continue
        if not x["base_cny"] or x["base_cny"] <= 0:
            dropped.append({**x, "ratio": None, "why": "基线价缺失"})
            continue
        r = to_cny(x["lk_usd"], "USD") / x["base_cny"]
        if not RATIO_LO <= r <= RATIO_HI:
            dropped.append({**x, "ratio": r, "why": "比值越界"})
            continue
        key = (round(x["lk_usd"], 4), round(x["base_cny"], 4))
        if key in seen:
            dropped.append({**x, "ratio": r, "why": "重复锚点"})
            continue
        seen.add(key)
        kept.append({**x, "ratio": r})

    by_cls, by_cat = {}, {}
    for x in kept:
        by_cls.setdefault(x["cls"], []).append(x["ratio"])
        if use_category and x["category"] != x["cls"] and x["category"] not in CATEGORY_BLOCKLIST:
            by_cat.setdefault(x["category"], []).append(x["ratio"])
    cls_f = {k: (clamp(statistics.median(v)), len(v)) for k, v in by_cls.items()}
    cat_f = {k: (clamp(statistics.median(v)), len(v))
             for k, v in by_cat.items() if len(v) >= MIN_CAT_ANCHORS}
    if use_category:
        cat_f.update({k: (f, 0) for k, (f, _) in MANUAL_CATEGORY.items()})
    return {"class": cls_f, "category": cat_f, "kept": kept, "dropped": dropped}


def pick_factor(factors, cls, category):
    if category in factors["category"]:
        f, n = factors["category"][category]
        return f, n, "category", category
    key = CLASS_FALLBACK.get(cls, cls)
    if key in factors["class"]:
        f, n = factors["class"][key]
        return f, n, "class", key
    return None


def concrete_line(quoted):
    if len(quoted) < 2:
        return None
    xs = sorted(quoted)
    ys = [quoted[x] for x in xs]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return slope, my - slope * mx
```

- [x] **Step 4：跑测试，确认通过**

```bash
PYTHONIOENCODING=utf-8 python -m pytest plan/斯里兰卡基价/temp/scripts/test_lk_phase2_core.py -q
```

⛔ **闸门 1**：`10 passed`。失败就只改 `lk_phase2_core.py`，**不准改测试的期望值**。

---

## Task 2：标定兰卡系数 `calibrate_lk.py` → `temp/lk_factors.json`

**Files:**
- Create: `plan/斯里兰卡基价/temp/scripts/calibrate_lk.py`
- Create（产物）: `plan/斯里兰卡基价/temp/lk_factors.json`

**Interfaces:**
- Consumes: `lk_phase2_core.calibrate/to_cny/lk_category`；`common_lk.MASTER_DB/ROOT/utf8_stdout`；`categories.category_of(res_Name, res_Class_Name) -> (category, scope)`（在 `plan/基价方案/temp/scripts/categories.py`，`common_lk` 会自动把该目录加进 sys.path）
- Produces: `lk_factors.json`，结构为 `{"cn_2026": {"class": {cls: [f, n]}, "category": {cat: [f, n]}, "kept": [...], "dropped": [...]}, "th_2026": {"class": {...}, "category": {}, ...}}`

- [x] **Step 1：写脚本**

```python
# -*- coding: utf-8 -*-
"""Phase 2a — 用 lk_2026 的 52 条报价对 cn_2026 / th_2026 标定兰卡系数 → temp/lk_factors.json。

cn_2026：大类 + 品类（品类需 ≥3 个锚点）；th_2026：只标大类（L3 兜底用）。
不写 price_factor 表（无 pack 列，会污染泰国系数）。

    python plan/斯里兰卡基价/temp/scripts/calibrate_lk.py
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common_lk as L  # noqa: E402
import lk_phase2_core as K  # noqa: E402
from categories import category_of  # noqa: E402

OUT = L.ROOT / "plan" / "斯里兰卡基价" / "temp" / "lk_factors.json"
SQL = """
SELECT r.res_ID, r.res_Name, r.res_Class_Name AS cls, COALESCE(r.res_Standard, '') AS standard,
       l.price AS lk_usd, o.price AS other_price, o.currency AS other_cur
FROM resource_price l
JOIN resource r USING (res_ID)
JOIN resource_price o ON o.res_ID = l.res_ID AND o.pack = ?
WHERE l.pack = 'lk_2026' AND l.price_kind = 'quote' AND o.price > 0
"""


def load(con, base_pack):
    out = []
    for r in con.execute(SQL, (base_pack,)):
        base_cat, scope = category_of(r["res_Name"], r["cls"])
        out.append({
            "res_ID": r["res_ID"], "name": r["res_Name"], "cls": r["cls"],
            "category": K.lk_category(r["res_Name"], r["cls"], base_cat, scope),
            "standard": r["standard"], "lk_usd": r["lk_usd"],
            "base_cny": K.to_cny(r["other_price"], r["other_cur"]),
        })
    return out


def main():
    L.utf8_stdout()
    con = sqlite3.connect(L.MASTER_DB)
    con.row_factory = sqlite3.Row
    result = {}
    for base in ("cn_2026", "th_2026"):
        anchors = load(con, base)
        res = K.calibrate(anchors, use_category=(base == "cn_2026"))
        result[base] = res
        print(f"=== {base}：锚点 {len(anchors)}，采用 {len(res['kept'])}，剔除 {len(res['dropped'])}")
        for k, (f, n) in sorted(res["class"].items()):
            print(f"  大类 {k:<6} factor={f:.3f} n={n}")
        for k, (f, n) in sorted(res["category"].items()):
            print(f"  品类 {k:<10} factor={f:.3f} n={n}")
        for d in res["dropped"]:
            ratio = "-" if d["ratio"] is None else f"{d['ratio']:.2f}"
            print(f"  剔除 {d['name']} {d['standard']} ratio={ratio} {d['why']}")
    con.close()
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("->", OUT)


if __name__ == "__main__":
    main()
```

- [x] **Step 2：运行**

```bash
PYTHONIOENCODING=utf-8 python plan/斯里兰卡基价/temp/scripts/calibrate_lk.py
```

⛔ **闸门 2**：输出必须与下表一致（factor 误差 ±0.005，n 必须相等）。这是写计划时用同一套规则算出来的预期值：

| 基线 | 层 | key | factor | n |
|---|---|---|---:|---:|
| cn_2026 | 大类 | 人工 | 0.774 | 3 |
| cn_2026 | 大类 | 材料 | 1.537 | 16 |
| cn_2026 | 大类 | 机械 | 0.889 | 11 |
| cn_2026 | 品类 | 混凝土砂浆 | 1.329 | 4 |
| cn_2026 | 品类 | 机械-泵焊搅拌 | 0.997 | 4 |
| cn_2026 | 品类 | 机械-土方 | 0.889 | 3 |
| cn_2026 | 品类 | 钢材-钢筋（专家定值） | 1.300 | 0 |
| cn_2026 | 品类 | 油料（专家定值） | 1.000 | 0 |
| cn_2026 | 品类 | 能源水电（专家定值） | 1.000 | 0 |
| cn_2026 | 品类 | 气体（专家定值） | 1.000 | 0 |
| th_2026 | 大类 | 人工 | 0.782 | 3 |
| th_2026 | 大类 | 材料 | 1.562 | 18 |
| th_2026 | 大类 | 机械 | 0.849 | 11 |

cn_2026 的「比值越界」剔除项应为这 7 条：φ50钢管扶手 23.26、内墙瓷砖 5.05、通体砖0.09m2以内 4.87、钢筋 6.89、发电机 7.67、污水泵 5.58、灰浆搅拌机 19.99。「砖瓦砌块」**不能**出现在品类里。

对不上就停止并把完整输出贴进执行日志，**不要调阈值去凑**。

---

## Task 3：瀑布派生 `derive_lk.py` → `resource_price(derived)`

**Files:**
- Create: `plan/斯里兰卡基价/temp/scripts/derive_lk.py`
- Create（产物）: `plan/斯里兰卡基价/temp/lk_unpriced.csv`
- Modify（DB）: `resource_price` 中 `pack='lk_2026' AND price_kind='derived'` 的行

**Interfaces:**
- Consumes: `lk_factors.json`（Task 2）；`lk_phase2_core.*`（Task 1）；`common_lk.PACK/PACK_CUTOFF/MASTER_DB/ROOT/utf8_stdout`
- Produces: derived 行。字段约定：`currency='USD'`、`tier='D'`、`price_kind='derived'`、`fx_rate=6.788`、`src_currency ∈ {CNY, THB, USD}`、`src_price=基线原价`（L1b 为 NULL）、`source_doc ∈ {cn_2026, th_2026, lk_2026 报价层}`。Task 4 的 verify 依赖这些字段。

- [x] **Step 1：写脚本**

```python
# -*- coding: utf-8 -*-
"""Phase 2b — lk_2026 派生层：兰卡锚点系数 × cn_2026 / th_2026 → resource_price(derived)。

瀑布（命中即停）：
  L1  兰卡报价（Phase 1 已落，原样保留，本脚本不碰）
  L1b 混凝土标号线性外推（由已报价 C25/C30/C35 拟合；cn_2026 的 C20<C15 倒挂，不能乘系数）
  L2  cn_2026(CNY) × 兰卡系数(品类→大类) ÷ 6.788 → USD
  L3  th_2026(THB) ÷ 5.0 × 兰卡/泰国大类系数 ÷ 6.788 → USD
  L9  留空 → temp/lk_unpriced.csv

幂等：写库前先删本包全部 derived 行。

    python plan/斯里兰卡基价/temp/scripts/derive_lk.py --dry-run
    python plan/斯里兰卡基价/temp/scripts/derive_lk.py
"""
import argparse
import csv
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common_lk as L  # noqa: E402
import lk_phase2_core as K  # noqa: E402
from categories import category_of  # noqa: E402

TEMP = L.ROOT / "plan" / "斯里兰卡基价" / "temp"
FACTORS = TEMP / "lk_factors.json"
UNPRICED = TEMP / "lk_unpriced.csv"

INSERT = (
    "INSERT INTO resource_price (res_ID, pack, country, currency, price, price_date, source,"
    " price_excl, price_incl, tax, tier, quote_ID, src_country, src_currency, src_price, src_unit,"
    " fx_rate, unit_factor, source_doc, supplier, contact, phone, address, remark, price_kind)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def make_row(rid, country, usd, source, src_cur, src_price, unit, source_doc, remark):
    return (rid, L.PACK, country, "USD", round(usd, 4), L.PACK_CUTOFF, source,
            None, None, None, "D", None, country, src_cur, src_price, unit,
            K.FX_CNY_PER_USD, 1.0, source_doc, None, None, None, None, remark, "derived")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    L.utf8_stdout()

    fac = json.loads(FACTORS.read_text(encoding="utf-8"))
    cn_f = fac["cn_2026"]
    th_f = {"class": fac["th_2026"]["class"], "category": {}}

    con = sqlite3.connect(L.MASTER_DB)
    con.row_factory = sqlite3.Row
    refs = {r[0]: (r[1] or 0) for r in con.execute(
        "SELECT res_ID, SUM(refs) FROM resource_usage GROUP BY res_ID")}
    total_refs = sum(refs.values())
    quoted = {r["res_ID"]: r["price"] for r in con.execute(
        "SELECT res_ID, price FROM resource_price WHERE pack=? AND price_kind='quote'", (L.PACK,))}
    cn = {r["res_ID"]: r for r in con.execute(
        "SELECT res_ID, price, country FROM resource_price WHERE pack='cn_2026' AND price>0")}
    th = {r["res_ID"]: r for r in con.execute(
        "SELECT res_ID, price, currency, country FROM resource_price WHERE pack='th_2026' AND price>0")}
    res = list(con.execute(
        "SELECT res_ID, res_Name, res_Class_Name AS cls, COALESCE(res_Standard,'') AS std, res_Unit"
        " FROM resource"))
    by_id = {r["res_ID"]: r for r in res}

    grades = {}
    for rid, usd in quoted.items():
        r = by_id[rid]
        g = K.concrete_grade(r["res_Name"], r["cls"])
        if g is not None and r["res_Unit"] == "m3":
            grades[g] = usd
    line = K.concrete_line(grades)
    print(f"混凝土拟合点 {sorted(grades.items())} → {line}")

    rows, unpriced = [], []
    stat = defaultdict(lambda: [0, 0])
    for r in res:
        rid, cls, unit, name = r["res_ID"], r["cls"], r["res_Unit"], r["res_Name"]
        g = K.concrete_grade(name, cls)
        layer, new = "L9", None
        if rid in quoted:
            layer = "L1"
        elif line and g is not None and unit == "m3":
            usd = line[0] * g + line[1]
            new = make_row(rid, "斯里兰卡", usd,
                           f"兰卡混凝土标号线性外推（C{min(grades)}~C{max(grades)} 报价拟合）",
                           "USD", None, unit, "lk_2026 报价层",
                           f"price = {line[0]:.4f} × {g} + {line[1]:.4f} = {usd:.4f}USD；"
                           f"拟合点 {sorted(grades.items())}")
            layer = "L1b"
        elif rid in cn:
            base_cat, scope = category_of(name, cls)
            pf = K.pick_factor(cn_f, cls, K.lk_category(name, cls, base_cat, scope))
            if pf:
                f, n, lvl, key = pf
                base = cn[rid]["price"]
                usd = K.cny_to_usd(base * f)
                new = make_row(rid, cn[rid]["country"] or "中国", usd,
                               f"cn_2026 × 兰卡{key}系数{f:.3f} ÷ {K.FX_CNY_PER_USD}",
                               "CNY", base, unit, "cn_2026",
                               f"cn_2026 {base:.4f}CNY/{unit} × {f:.4f}（{lvl}:{key}，n={n}）"
                               f" ÷ {K.FX_CNY_PER_USD} = {usd:.4f}USD")
                layer = "L2"
        elif rid in th and th[rid]["currency"] == "THB":
            pf = K.pick_factor(th_f, cls, cls)
            if pf:
                f, n, lvl, key = pf
                base = th[rid]["price"]
                usd = K.cny_to_usd(K.to_cny(base, "THB") * f)
                new = make_row(rid, th[rid]["country"] or "泰国", usd,
                               f"th_2026 ÷ {K.FX_THB_PER_CNY} × 兰卡/泰国{key}系数{f:.3f} ÷ {K.FX_CNY_PER_USD}",
                               "THB", base, unit, "th_2026",
                               f"th_2026 {base:.4f}THB/{unit} ÷ {K.FX_THB_PER_CNY} × {f:.4f}"
                               f"（{lvl}:{key}，n={n}）÷ {K.FX_CNY_PER_USD} = {usd:.4f}USD")
                layer = "L3"
        if new:
            rows.append(new)
        if layer == "L9":
            unpriced.append((rid, cls, name, r["std"], unit, refs.get(rid, 0),
                             f"{cls}：cn_2026 / th_2026 均无价"))
        stat[layer][0] += 1
        stat[layer][1] += refs.get(rid, 0)

    print(f"{'层':<5}{'资源数':>8}{'refs':>10}{'占比':>8}")
    for k in ("L1", "L1b", "L2", "L3", "L9"):
        n, rf = stat[k]
        print(f"{k:<5}{n:>8}{rf:>10}{rf / total_refs:>8.1%}")
    priced = sum(stat[k][1] for k in ("L1", "L1b", "L2", "L3"))
    print(f"已定价 refs 覆盖 {priced}/{total_refs} = {priced / total_refs:.1%}；将写 derived {len(rows)} 行")

    unpriced.sort(key=lambda x: -x[5])
    with UNPRICED.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["res_ID", "类别", "名称", "规格", "单位", "refs", "原因"])
        w.writerows(unpriced)
    print("->", UNPRICED)

    if args.dry_run:
        print("[dry-run] 未写库")
        con.close()
        return
    with con:
        con.execute("DELETE FROM resource_price WHERE pack=? AND price_kind='derived'", (L.PACK,))
        con.executemany(INSERT, rows)
    n = con.execute("SELECT COUNT(*) FROM resource_price WHERE pack=?", (L.PACK,)).fetchone()[0]
    con.close()
    print(f"已写入 derived {len(rows)} 行；lk_2026 现共 {n} 行")


if __name__ == "__main__":
    main()
```

- [x] **Step 2：dry-run**

```bash
PYTHONIOENCODING=utf-8 python plan/斯里兰卡基价/temp/scripts/derive_lk.py --dry-run
```

⛔ **闸门 3a**（dry-run 输出必须同时满足）：
- 混凝土拟合点为 `[(25, 93.6...), (30, 99.3...), (35, 105.0...)]`
- L1 = 52
- L1b = 3（C15/C20/C40）
- L2 = 9,491
- L3 = 1,281
- L9 = 3,160
- 已定价 refs 覆盖 362199/401431 = 90.2%，将写 derived 10,775 行
- `lk_unpriced.csv` 已生成，行数 3,160（不含表头）

（以上是写计划时在数据库副本上实跑的结果。任何一项不同，说明库在此期间被改过，停止。）

- [x] **Step 3：正式写库**

```bash
PYTHONIOENCODING=utf-8 python plan/斯里兰卡基价/temp/scripts/derive_lk.py
```

- [x] **Step 4：再跑一遍，验证幂等**

```bash
PYTHONIOENCODING=utf-8 python plan/斯里兰卡基价/temp/scripts/derive_lk.py
```

⛔ **闸门 3b**：两次运行最后一行里的「lk_2026 现共 N 行」完全相同，且 N = 52 + derived 行数。

---

## Task 4：独立验证 `verify_lk_phase2.py` + 复核清单

**Files:**
- Create: `plan/斯里兰卡基价/temp/scripts/verify_lk_phase2.py`
- Create（产物）: `plan/斯里兰卡基价/temp/lk_top200_review.csv`

**Interfaces:**
- Consumes: `temp/lk_phase1_snapshot.json`（Task 0）、Task 3 写入的 derived 行、`src/price_api.py` 的 `_conn()` 和 `_default_pack(conn)`

- [x] **Step 1：写脚本**

```python
# -*- coding: utf-8 -*-
"""Phase 2 验证 —— lk_2026 派生层的隔离性、自洽性、阶梯单调性，并导出头部复核清单。

    python plan/斯里兰卡基价/temp/scripts/verify_lk_phase2.py
"""
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common_lk as L  # noqa: E402
import lk_phase2_core as K  # noqa: E402

TEMP = L.ROOT / "plan" / "斯里兰卡基价" / "temp"
SNAP = json.loads((TEMP / "lk_phase1_snapshot.json").read_text(encoding="utf-8"))
REVIEW = TEMP / "lk_top200_review.csv"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")


def main():
    L.utf8_stdout()
    con = sqlite3.connect(L.MASTER_DB)
    con.row_factory = sqlite3.Row
    q = lambda s, *p: con.execute(s, p).fetchone()  # noqa: E731

    lk_q = list(q("SELECT COUNT(*), ROUND(SUM(price),4) FROM resource_price"
                  " WHERE pack='lk_2026' AND price_kind='quote'"))
    check("1 报价层未被改动", lk_q == SNAP["lk_quote"], f"{lk_q} vs {SNAP['lk_quote']}")
    th = list(q("SELECT COUNT(*), ROUND(SUM(price),2) FROM resource_price WHERE pack='th_2026'"))
    cn = list(q("SELECT COUNT(*), ROUND(SUM(price),2) FROM resource_price WHERE pack='cn_2026'"))
    check("2 th_2026/cn_2026 未被改动", th == SNAP["th_2026"] and cn == SNAP["cn_2026"], f"th={th} cn={cn}")
    status = dict(con.execute("SELECT pack, status FROM price_pack").fetchall())
    check("3 包状态不变（lk inactive）", status == SNAP["status"], str(status))

    bad = q("SELECT COUNT(*) FROM resource_price WHERE pack='lk_2026' AND"
            " (currency<>'USD' OR price IS NULL OR price<=0 OR price_kind NOT IN ('quote','derived'))")[0]
    dup = q("SELECT COUNT(*) FROM (SELECT res_ID FROM resource_price WHERE pack='lk_2026'"
            " GROUP BY res_ID HAVING COUNT(*)>1)")[0]
    check("4 行级合法（USD、>0、无重复资源）", bad == 0 and dup == 0, f"bad={bad} dup={dup}")

    conc = {}
    for r in con.execute("SELECT r.res_Name, p.price FROM resource_price p JOIN resource r USING(res_ID)"
                         " WHERE p.pack='lk_2026' AND r.res_Class_Name='材料' AND r.res_Unit='m3'"):
        m = re.match(r"^C(\d{2})$", (r["res_Name"] or "").strip())
        if m:
            conc.setdefault(int(m.group(1)), []).append(r["price"])
    seq = [(g, max(v)) for g, v in sorted(conc.items())]
    mono = all(seq[i][1] < seq[i + 1][1] for i in range(len(seq) - 1))
    check("5 混凝土标号单调", mono and len(seq) >= 4, str([(g, round(p, 2)) for g, p in seq]))

    lab = {(r["res_Name"], r["std"]): r["price"] for r in con.execute(
        "SELECT r.res_Name, COALESCE(r.res_Standard,'') AS std, p.price FROM resource_price p"
        " JOIN resource r USING(res_ID) WHERE p.pack='lk_2026' AND r.res_Class_Name='人工'")}
    ladder = [lab.get((n, "")) for n in ("普工", "技工", "高级技工", "工长")]
    ok = None not in ladder and all(ladder[i] < ladder[i + 1] for i in range(3))
    check("6 人工阶梯 普工<技工<高级技工<工长", ok, str([round(x, 2) if x else x for x in ladder]))

    out_of_range = 0
    for r in con.execute("SELECT price, src_price, src_currency FROM resource_price"
                         " WHERE pack='lk_2026' AND price_kind='derived' AND src_price IS NOT NULL"):
        f = K.to_cny(r["price"], "USD") / K.to_cny(r["src_price"], r["src_currency"])
        if not (K.FACTOR_MIN - 1e-6 <= f <= K.FACTOR_MAX + 1e-6):
            out_of_range += 1
    check("7 派生价/基线价 反推系数全在 [0.4, 3.0]", out_of_range == 0, f"越界 {out_of_range}")

    total = q("SELECT SUM(refs) FROM resource_usage")[0]
    cov = q("SELECT COUNT(DISTINCT p.res_ID), SUM(u.refs) FROM resource_price p"
            " LEFT JOIN (SELECT res_ID, SUM(refs) refs FROM resource_usage GROUP BY res_ID) u USING(res_ID)"
            " WHERE p.pack='lk_2026'")
    check("8 覆盖 ≥ 89.5% refs", cov[1] / total >= 0.895,
          f"{cov[0]} 资源 / {cov[1]}/{total} refs = {cov[1] / total:.1%}")

    sys.path.insert(0, str(L.ROOT / "src"))
    import price_api as PA
    dp = PA._default_pack(PA._conn())
    check("9 前端默认包仍是 th_2026", dp == "th_2026", str(dp))

    rows = con.execute("""
        SELECT p.res_ID, r.res_Class_Name, r.res_Name, COALESCE(r.res_Standard,''), r.res_Unit,
               u.refs, p.price_kind, p.source_doc, ROUND(p.price,4), ROUND(p.price*?,4),
               cn.price, ROUND(th.price/?,4), p.source
        FROM resource_price p JOIN resource r USING(res_ID)
        LEFT JOIN (SELECT res_ID, SUM(refs) refs FROM resource_usage GROUP BY res_ID) u USING(res_ID)
        LEFT JOIN resource_price cn ON cn.res_ID=p.res_ID AND cn.pack='cn_2026'
        LEFT JOIN resource_price th ON th.res_ID=p.res_ID AND th.pack='th_2026'
        WHERE p.pack='lk_2026' AND p.price_kind='derived'
        ORDER BY u.refs DESC LIMIT 200""", (K.FX_CNY_PER_USD, K.FX_THB_PER_CNY)).fetchall()
    with REVIEW.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["res_ID", "类别", "名称", "规格", "单位", "refs", "price_kind", "来源包",
                    "兰卡USD", "折CNY", "cn_2026 CNY", "th_2026折CNY", "来源说明"])
        w.writerows([tuple(r) for r in rows])
    print("->", REVIEW)
    con.close()
    print(f"\n通过 {sum(results)}/{len(results)}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
```

- [x] **Step 2：运行**

```bash
PYTHONIOENCODING=utf-8 python plan/斯里兰卡基价/temp/scripts/verify_lk_phase2.py
```

⛔ **闸门 4**：`通过 9/9`，退出码 0。

- 检查 1/2/3 失败，说明碰了不该碰的数据：**立即停止**，并在执行日志里写明，用 Task 0 的备份回滚：

```bash
PYTHONIOENCODING=utf-8 python -c "
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect('db/resource_master.sqlite')
src.backup(dst); dst.close(); src.close(); print('restored')
" "db/backup/resource_master.sqlite.pre-lk-phase2-<时间戳>.bak"
```

- 检查 5/6/7/8 失败：停止，把输出贴进执行日志，**不要改代码去凑**，留给用户早上判断。

- [x] **Step 3：人工抽查 5 条**（只读，结果写进执行日志）

打开 `temp/lk_top200_review.csv`，找到下面 5 类资源，把「兰卡USD」和「折CNY」抄进执行日志：水泥、中砂/砂子、柴油、电、C20（C20 引用少，不在清单里的话就直接去库里查 `pack='lk_2026'` 的那一行）。参考值（副本实跑）：柴油 1.3229、电 0.1011、钢筋 φ10以外 0.7431、C20 87.89 USD。只做记录，**不改任何数据**。

---

## Task 5：文档与包说明更新

**Files:**
- Modify（DB）: `price_pack` 里 `pack='lk_2026'` 的 `note`
- Modify: `plan/斯里兰卡基价/斯里兰卡基价方案.md`（顶部状态行 + 文末追加一节）
- Modify: `db/CLAUDE.md` 的价格包表格里 `lk_2026` 那一行
- Modify: `db/INDEX.md` 里 `resource_price` 和 `price_pack` 两行的计数

- [x] **Step 1：更新 `price_pack.note`**（只改 lk_2026 这一行）

```bash
PYTHONIOENCODING=utf-8 python -c "
import sqlite3
c = sqlite3.connect('db/resource_master.sqlite')
note = ('以斯里兰卡 Mireka 项目成本测算表（CostSpread 批次 20260928-01）为锚点的斯里兰卡参考基价。'
        'USD 本位，fx_json={\"CNY\":6.788,\"LKR\":336.0}。'
        'L1 报价层 52 条（price_kind=quote）；L1b 混凝土按已报价标号线性外推；'
        'L2 cn_2026×兰卡系数÷6.788；L3 th_2026÷5.0×兰卡/泰国系数÷6.788（均为 price_kind=derived, tier=D）。'
        '系数由 52 条锚点对基线的比值中位数标定（比值 [0.3,4.0] 之外剔除），明细见 plan/斯里兰卡基价/temp/lk_factors.json。'
        '主材/设备/艘班等两基线均无价者留空。口径详见 plan/斯里兰卡基价/。')
n = c.execute(\"update price_pack set note=? where pack='lk_2026'\", (note,)).rowcount
c.commit(); print('updated', n)
"
```

预期输出：`updated 1`。

- [x] **Step 2：在 `斯里兰卡基价方案.md` 中**
  - 把第 3 行 `> 状态：Phase 1 已执行（报价层）。` 改成 `> 状态：Phase 1（报价层）+ Phase 2（派生层）已执行。`
  - 把第 5 行 `> 派生层（照搬泰国方案做全库推算）**尚未做**，留待 Phase 2。` 改成 `> Phase 2 见文末 §9。`
  - 在文末追加 `## 9. Phase 2 派生层（<执行日期>）`，内容依次为：
    1. 系数表，用 Task 2 的实际输出
    2. 瀑布分层表（层 / 资源数 / refs / 占比），用 Task 3 正式运行的实际输出
    3. verify 9 项结果
    4. 已知问题（原样写入下面 4 条）：
       - `cn_2026` 的无规格钢筋 = 0.725 CNY/kg，疑似数据错误（正常约 3.5~4）；兰卡侧已有报价，不受影响，但泰国/中国包值得复查
       - `cn_2026` 的 C20（312.62）低于 C15（459.36），基线倒挂；兰卡侧已用标号线性外推规避
       - 材料大类系数 1.537 由 16 个锚点标定，锚点偏装修材料（瓷砖、标识、地板），大宗材料（砂石、水泥、钢材）可能被高估，需要按 `lk_top200_review.csv` 复核
       - 专家定值（`MANUAL_CATEGORY`）：钢材-钢筋 1.3（由兰卡钢筋报价反推，派生出的 φ10以外 0.743 USD/kg 与报价 0.736 吻合）；油料/能源水电/气体 1.0 为无锚点平价，**需要兰卡当地询价来替换**
       - 留空资源清单见 `temp/lk_unpriced.csv`
    5. 新增脚本清单：`lk_phase2_core.py` / `test_lk_phase2_core.py` / `calibrate_lk.py` / `derive_lk.py` / `verify_lk_phase2.py`，以及 Task 0 的备份路径

- [x] **Step 3：`db/CLAUDE.md`** 价格包表格中 `lk_2026` 那一行：「行数」改为实际总行数，「口径」改为 `斯里兰卡参考基价 2026：报价层 52 + 派生层（cn_2026/th_2026 × 兰卡系数），USD`。只改这一行，其他内容不动。

- [x] **Step 4：`db/INDEX.md`**：`resource_price` 行的总数和 `lk_2026` 分包计数改成实际值；`price_pack` 行中 `lk_2026` 的描述把「只含报价层 52 条」改成「报价层 52 + 派生 N 条」。只改这两处。

- [x] **Step 5：用 grep 确认**

```bash
grep -n "lk_2026" db/CLAUDE.md db/INDEX.md
```

输出里不应再出现「只含报价层」「无派生」这些旧说法。

---

## Task 6：收尾与交接

- [x] **Step 1：最后再跑一次 verify**，确认文档更新后数据仍然正常

```bash
PYTHONIOENCODING=utf-8 python plan/斯里兰卡基价/temp/scripts/verify_lk_phase2.py
```

预期：`通过 9/9`。

- [x] **Step 2：在本文末尾「执行日志」中写交接摘要**，必须包含以下内容：
  - 备份路径
  - 系数表（实际值）
  - 瀑布分层（实际值）
  - verify 结果
  - Task 4 Step 3 的 5 条抽查值
  - 每个闸门的实际数值
  - 任何偏离本计划的地方（如果没有，写「无偏离」）

- [x] **Step 3：明确不做的事**（写进交接摘要，留给用户决定）：
  - 不把 `lk_2026` 设为 active（要先改 `_default_pack` 的选包逻辑）
  - 不回写 5 册 `Consumption` / `Norm`
  - 不做跨维度 xfactor（木模板侧模 m↔m2、空心砌块 m2↔m3）
  - 不把专业分包/间接费接进主数据
  - 不修 `cn_2026` 的钢筋和 C20 数据

---

## 执行日志

（执行者在这里追加。格式：`[时间] Task N Step M：结果 / 闸门数值 / 异常`）

---

## 交接摘要（2026-09-29 01:10~01:25 执行完毕）

### 闸门实测值

| 闸门 | 预期 | 实测 |
|---|---|---|
| 0 库状态 | lk_quote=52、lk_other=0、th=10818、cn=9536、status 三项一致 | 全部一致（`lk_quote=[52, 3465.6879]`） |
| 1 单元测试 | 10 passed | **10 passed** |
| 2 系数标定 | 13 项 factor/n 全中；7 条越界；无「砖瓦砌块」 | 全部一致，逐项核对通过 |
| 3a dry-run | L1 52 / L1b 3 / L2 9491 / L3 1281 / L9 3160；覆盖 90.2%；derived 10775；CSV 3160 行 | 全部一致 |
| 3b 幂等 | 两次最后一行相同 | 「已写入 derived 10775 行；lk_2026 现共 10827 行」×3 次完全相同 |
| 4 验证 | 9/9，退出码 0 | **9/9，EXIT=0** |

### 备份路径

`db/backup/resource_master.sqlite.pre-lk-phase2-20260929_011031.bak`

### 系数表（`temp/lk_factors.json`）

cn_2026 大类：人工 0.774(n=3) / 材料 1.537(n=16) / 机械 0.889(n=11)
cn_2026 品类：混凝土砂浆 1.329(n=4) / 机械-泵焊搅拌 0.997(n=4) / 机械-土方 0.889(n=3)
cn_2026 专家定值：钢材-钢筋 1.3 / 油料 1.0 / 能源水电 1.0 / 气体 1.0（n=0）
th_2026 大类：人工 0.782(n=3) / 材料 1.562(n=18) / 机械 0.849(n=11)

### 瀑布分层（实测）

| 层 | 资源数 | refs | 占比 |
|---|---:|---:|---:|
| L1 | 52 | 51,232 | 12.8% |
| L1b | 3 | 2 | 0.0% |
| L2 | 9,491 | 294,419 | 73.3% |
| L3 | 1,281 | 16,546 | 4.1% |
| L9 | 3,160 | 39,232 | 9.8% |

覆盖 362,199/401,431 = 90.2%；`lk_2026` 共 10,827 行（52 quote + 10,775 derived）。

### Task 4 Step 3 抽查值

| 资源 | 兰卡 USD | 折 CNY | 来源 |
|---|---|---|---|
| 柴油 res5105 /kg | 1.3229 | 8.9798 | L2（油料 1.0） |
| 电 res6707 /kW·h | 0.1011 | 0.6863 | L2（能源水电 1.0） |
| 钢筋 φ10以外 res9419 /kg | 0.7431 | 5.0442 | L2（钢材-钢筋 1.3） |
| 钢筋（报价）res9415 /kg | 0.7356 | 4.9934 | L1 |
| C20 res145 /m3 | 87.8929 | 596.617 | L1b |
| 中砂 res1146 /m3 | 30.7804 | 208.9374 | L2（材料 1.537） |
| 水泥 32.5 res5591 /t | 70.4186 | 478.0015 | L2 |
| 水泥 32.5级 res5592 /t | 190.1982 | 1291.0653 | L2 |
| 水泥 425 res5595 /t | 181.1412 | 1229.5846 | L2 |

钢筋派生值 0.7431 与 L1 报价 0.7356 吻合（±1%），验证了专家定值 1.3 的取法。

### 偏离本计划的地方

1. **Task 0 Step 1 未按字面执行**：`tasklist | findstr /I "python pythonw"` 会命中 `start.py`(29080)、两个
   ComfyUI(33656/11100)、fastexcel MCP(5200)。改为查进程命令行 + 检查有无 `resource_master.sqlite-journal`/`-wal`，
   确认无进程在写库。判据等效，做法不同。
2. **Task 5 Step 2 的「已知问题」多写了 1 条**（原计划说 4 条、实际列 5 条，我写了 6 条）：新增第 5 条
   「同一产品在 cn_2026 里基线不一致」（水泥 32.5 的 65~190 USD/t 分散）。这是 Task 4 Step 3 抽查时才暴露的，
   计划写作时未预料。只记录，未改数据。
3. 计划文末的 24 个 `- [ ]` 已按计划要求全部勾选为 `- [x]`。

### 明确不做的事（留给用户决定）

- 不把 `lk_2026` 设为 active（要先改 `_default_pack` 的选包逻辑，否则定额导出会按字典序偷偷换成兰卡价）
- 不回写 5 册 `Consumption` / `Norm`（现为泰国价）
- 不做跨维度 xfactor（木模板侧模 m↔m2、空心砌块 m2↔m3、机械 台班↔台）
- 不把专业分包/间接费接进主数据
- 不修 `cn_2026` 的钢筋（0.725）与 C20 倒挂
- 不补 3,160 条留空资源（清单 `temp/lk_unpriced.csv`，refs 前列为艘班与大宗材料）

### 交付物清单

| 路径 | 内容 |
|---|---|
| `plan/斯里兰卡基价/temp/scripts/lk_phase2_core.py` | 纯函数模块 |
| `plan/斯里兰卡基价/temp/scripts/test_lk_phase2_core.py` | 10 项单元测试 |
| `plan/斯里兰卡基价/temp/scripts/calibrate_lk.py` | 标定 |
| `plan/斯里兰卡基价/temp/scripts/derive_lk.py` | 瀑布派生 |
| `plan/斯里兰卡基价/temp/scripts/verify_lk_phase2.py` | 验证 |
| `plan/斯里兰卡基价/temp/lk_factors.json` | 系数表 |
| `plan/斯里兰卡基价/temp/lk_phase1_snapshot.json` | Phase 1 快照 |
| `plan/斯里兰卡基价/temp/lk_unpriced.csv` | 留空清单 3,160 行 |
| `plan/斯里兰卡基价/temp/lk_top200_review.csv` | 头部 200 条复核清单 |

---

## 追加：补锚点（2026-09-29，Phase 2 之后）

**来源**：`F:\BaiduSyncdisk\5.报价\1 报价项目\2024-7 斯里兰卡保障房项目\4 报价书\3 市场价\2 市场价\副本Labour,Material,Machinery Update List 11July2024(1).xlsx`
（LABOUR / MATERIAL / MC&EQ 三表第 1 行标了「提取价格」列）

**做法**：抽出 157 条 → 英译中 → 匹配主数据 94 条（56 个资源）→ 入 price_quote/quote_match → 重跑标定与派生。

**闸门**：Task1 单测 10 passed（未改动）；verify 9/9（**中间失败过一次检查 5**，见下）。

| 项 | 补锚点前 | 补锚点后 |
|---|---:|---:|
| 报价层锚点 | 52 | **94** |
| L1 refs 占比 | 12.8% | **16.9%** |
| L1b（混凝土外推） | 3 | 0（六个标号都有真报价） |
| lk_2026 总行数 | 10,827 | **10,830** |
| refs 覆盖 | 90.2% | 90.2% |

**检查 5 失败与裁定**：混凝土 C25/C30/C35 两个来源都有价，混合取中位数得到 `C20 104.29 > C25 102.17` 倒挂。
两套序列各自单调、市场表高 18%，差异在口径（Mireka 标了「不含泵送费」）。
用户裁定**统一采用 2024-07 市场表序列**，实现为 `common_lk.CONCRETE_PREFER_SOURCE` 的源优先级规则。
修正后检查 5 通过：`[(15,98.57),(20,104.29),(25,110.71),(30,114.11),(35,121.43),(40,125.0)]`。

**偏离原计划的地方**：
1. `verify_lk_phase2.py` 的检查 1 依赖 `lk_phase1_snapshot.json`。报价层按设计扩容（52→94），
   旧快照必然对不上。**重取了快照**（`note` 字段写明了原值 `lk_quote=[52, 3465.6879]`），属设计变更不是绕过。
2. `price_lk.py` 两处改动：报价源放开为 `LK_SOURCE_DOCS`；候选数为偶数时改用**真中位数**
   （原 `priced[len//2]` 是上中位，n=2 时会系统性偏高——补锚点后人工档位大量出现 n=2）。
3. 备份：`db/backup/resource_master.sqlite.pre-lk-anchors-20260929_014649.bak`。

**口径与验证详见** `斯里兰卡基价方案.md` §10。
