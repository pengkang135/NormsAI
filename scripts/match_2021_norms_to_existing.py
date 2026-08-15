"""
将A册2021定额逐条匹配到现有叶章节。

策略（norm级别）:
1. 每条2021定额 → 找到所属域(A_MAP)
2. 在域内同时匹配: a) 叶章节名 b) 该章节下现有定额名
3. 取最佳得分，逐条更新Norm.chap_ID
4. 删除所有2021章节
"""
import sqlite3, shutil, time, re
from pathlib import Path
from difflib import SequenceMatcher
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "db"
A_DB = DB_DIR / "企业定额_A册_建筑装饰.sqlite"

A_MAP = {
    131000000: 1000000,
    132000000: 2000000,
    133000000: 3000000,
    134000000: 6000000,
    135000000: 4000000,
    136000000: 7000000,
    137000000: 8000000,
    138000000: 13000000,
    139000000: 10000000,
    140000000: 12000000,
    141000000: 20000000,
    142000000: 21000000,
    143000000: 22000000,
    144000000: 23000000,
    145000000: 24000000,
    146000000: 33000000,
}

UNIT_RE = re.compile(r'\s*(m[²³23]?|kg|t|mm|cm|m|km|个|套|座|根|块|片|条|台|组|项|元|%|‰)\s*$', re.IGNORECASE)
PAREN_RE = re.compile(r'[（(][^)）]*[)）]$')
CODE_RE = re.compile(r'^[A-Za-z](\.\d+)+[\s]+')
CN_PREFIX = re.compile(r'^[一二三四五六七八九十]+[、．.\s)]*')

def clean_name(name):
    name = str(name or '')
    name = PAREN_RE.sub('', name)
    name = UNIT_RE.sub('', name)
    return name.strip()

def scode(name):
    m = CODE_RE.match(name)
    return name[m.end():].strip() if m else name.strip()

def strip_cn_num(name):
    m = CN_PREFIX.match(name)
    return name[m.end():].strip() if m else name.strip()

def find_map_key(conn, chap_id):
    cur = chap_id
    while cur and cur > 0:
        if cur in A_MAP:
            return cur
        row = conn.execute("SELECT chap_PID FROM chapter WHERE chap_ID=?", (cur,)).fetchone()
        if not row or not row[0]:
            return None
        cur = row[0]
    return None

def get_domain_leaves(conn, parent_id):
    result = []
    for cid, cname, ccode in conn.execute(
        "SELECT chap_ID, chap_Name, chap_code FROM chapter WHERE chap_PID=?", (parent_id,)
    ).fetchall():
        sub = conn.execute("SELECT COUNT(*) FROM chapter WHERE chap_PID=?", (cid,)).fetchone()[0]
        if sub > 0:
            result.extend(get_domain_leaves(conn, cid))
        else:
            if conn.execute("SELECT COUNT(*) FROM Norm WHERE chap_ID=?", (cid,)).fetchone()[0] > 0:
                result.append((cid, cname, ccode))
    return result

def build_norm_index(conn, leaf_chapters):
    """为每个叶章节预加载其下定额名列表"""
    index = {}
    for cid, _, _ in leaf_chapters:
        norms = conn.execute("SELECT norm_Name FROM Norm WHERE chap_ID=?", (cid,)).fetchall()
        index[cid] = [clean_name(n[0]) for n in norms]
    return index

def match_score(norm_name, target_name):
    """计算两条名称的匹配得分"""
    a = clean_name(norm_name)
    b = clean_name(target_name)
    score = SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:
        score = max(score, 0.85)
    # 去除中文序号前缀后再比一次
    a2 = strip_cn_num(a)
    b2 = strip_cn_num(b)
    if a2 != a or b2 != b:
        s2 = SequenceMatcher(None, a2, b2).ratio()
        if a2 in b2 or b2 in a2:
            s2 = max(s2, 0.85)
        score = max(score, s2)
    return score

def backup_db(db_path):
    d = db_path.parent / "backup"
    d.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = d / f"{db_path.stem}.pre-norm-redist-{ts}.bak"
    shutil.copy2(db_path, bak)
    return bak

def main():
    print("=" * 70)
    print("A册: 2021定额逐条匹配到现有叶章节 (norm级别 v2)")
    print("=" * 70)

    bak = backup_db(A_DB)
    print(f"[BACKUP] {bak.name}")

    conn = sqlite3.connect(str(A_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # 预加载各域叶章节 + 定额名索引
    domain_leaves = {}
    domain_norm_index = {}
    for k2021, k_existing in A_MAP.items():
        leaves = get_domain_leaves(conn, k_existing)
        domain_leaves[k2021] = leaves
        domain_norm_index[k2021] = build_norm_index(conn, leaves)
    total_leaves = sum(len(v) for v in domain_leaves.values())
    print(f"域内现有叶章节总数: {total_leaves}")

    norms_2021 = conn.execute("""
        SELECT n.norm_ID, n.norm_Code, n.norm_Name, n.chap_ID, c.chap_Name as chap_name
        FROM Norm n
        JOIN chapter c ON c.chap_ID = n.chap_ID
        WHERE n.chap_ID >= 130000000 AND n.chap_ID < 200000000
    """).fetchall()
    print(f"2021定额总数: {len(norms_2021)}")

    # norm_ID → target_chap_ID
    norm_mapping = {}
    no_match = []
    no_domain = []
    stats = defaultdict(lambda: {"total": 0, "matched": 0, "weak": 0})

    for norm in norms_2021:
        nid, ncode, nname, chap_id, chap_name = norm
        map_key = find_map_key(conn, chap_id)
        if map_key is None or map_key not in domain_leaves:
            no_domain.append((nid, ncode, nname, chap_name))
            continue

        leaves = domain_leaves[map_key]
        norm_index = domain_norm_index[map_key]
        stats[map_key]["total"] += 1

        # 对每个叶章节计算最佳匹配分
        best_cid, best_score, best_source = None, 0, ""

        for cid, cname, _ in leaves:
            # 匹配叶章节名
            s = match_score(nname, scode(cname))
            if s > best_score:
                best_score = s
                best_cid = cid
                best_source = f"chapter:{scode(cname)}"

            # 匹配该章节下现有定额名
            for ename in norm_index.get(cid, []):
                s = match_score(nname, ename)
                if s > best_score:
                    best_score = s
                    best_cid = cid
                    best_source = f"norm:{ename}"

        if best_score >= 0.6:
            norm_mapping[nid] = (best_cid, best_score)
            if best_score >= 0.85:
                stats[map_key]["matched"] += 1
            else:
                stats[map_key]["weak"] += 1
        else:
            no_match.append((nid, ncode, clean_name(nname), chap_name, best_score, best_cid, best_source))

    # 兜底: 无域定额 → 追溯域，取该域第一个叶章节
    domain_fallback = 0
    for item in no_domain:
        nid, ncode, nname, chap_name = item
        # 尝试从chap_ID追溯
        orig_chap = conn.execute(
            "SELECT chap_ID FROM Norm WHERE norm_ID=?", (nid,)
        ).fetchone()
        if orig_chap:
            mk = find_map_key(conn, orig_chap[0])
            if mk and mk in domain_leaves and domain_leaves[mk]:
                norm_mapping[nid] = (domain_leaves[mk][0][0], 0.01)
                domain_fallback += 1

    # 兜底匹配低分项 (best_id存在但score<0.6)
    fallback_count = 0
    for item in no_match:
        nid, ncode, cn, chap_name, score, best_id, source = item
        if best_id:
            norm_mapping[nid] = (best_id, score)
            fallback_count += 1

    # 完全无匹配: 取域内第一个叶章节
    zero_fallback = 0
    for item in no_match:
        if item[5] is None:  # best_id is None
            nid, ncode, cn, chap_name, score, _, _ = item
            orig_chap = conn.execute(
                "SELECT chap_ID FROM Norm WHERE norm_ID=?", (nid,)
            ).fetchone()
            if orig_chap:
                mk = find_map_key(conn, orig_chap[0])
                if mk and mk in domain_leaves and domain_leaves[mk]:
                    norm_mapping[nid] = (domain_leaves[mk][0][0], 0.0)
                    zero_fallback += 1

    mapped_total = len(norm_mapping)
    print(f"\n匹配结果:")
    print(f"  高分匹配(>=0.85): {sum(1 for v in norm_mapping.values() if v[1] >= 0.85)} 条")
    print(f"  中分匹配(0.6-0.85): {sum(1 for v in norm_mapping.values() if 0.6 <= v[1] < 0.85)} 条")
    print(f"  兜底匹配(<0.6): {fallback_count} 条")
    print(f"  域兜底: {domain_fallback} 条")
    print(f"  零分兜底: {zero_fallback} 条")
    print(f"  总计已映射: {mapped_total} / {len(norms_2021)}")

    # 无域定额
    if no_domain:
        print(f"\n--- 无域定额({len(no_domain)}条) ---")
        by_ch = defaultdict(list)
        for item in no_domain:
            by_ch[item[3]].append(item)
        for ch, items in sorted(by_ch.items()):
            print(f"  [{ch}] {len(items)}条:")
            for nid, ncode, nname, _ in items[:5]:
                print(f"    {ncode} '{nname}'")

    # 低分兜底样例
    low_score = [(nid, nc, cn, ch, s, cid, src)
                 for nid, nc, cn, ch, s, cid, src in no_match if s > 0 and s < 0.6]
    if low_score:
        print(f"\n--- 低分兜底匹配样例 (前15条) ---")
        for nid, ncode, cn, chap_name, score, best_id, source in low_score[:15]:
            br = conn.execute("SELECT chap_Name FROM chapter WHERE chap_ID=?", (best_id,)).fetchone()
            target = scode(br[0]) if br else "???"
            print(f"  {ncode} '{cn}' → {target} [{score:.2f}] via {source}")

    # 高分匹配样例
    high_score = [(nid, cid, s) for nid, (cid, s) in norm_mapping.items() if s >= 0.85]
    print(f"\n--- 高分匹配样例 (前15条) ---")
    for i, (nid, cid, score) in enumerate(high_score[:15]):
        nr = conn.execute("SELECT norm_Code, norm_Name FROM Norm WHERE norm_ID=?", (nid,)).fetchone()
        ch = conn.execute("SELECT chap_Name FROM chapter WHERE chap_ID=?", (cid,)).fetchone()
        print(f"  {nr[0]} '{nr[1]}' → {ch[0]}")

    # ---- 逐条更新 ----
    print(f"\n--- 迁移: 逐条更新Norm.chap_ID ---")
    by_target = defaultdict(list)
    for nid, (target_cid, _) in norm_mapping.items():
        by_target[target_cid].append(nid)

    total_updated = 0
    for target_cid, nid_list in by_target.items():
        placeholders = ','.join('?' * len(nid_list))
        n = conn.execute(
            f"UPDATE Norm SET chap_ID=? WHERE norm_ID IN ({placeholders})",
            [target_cid] + nid_list
        ).rowcount
        total_updated += n
    conn.commit()
    print(f"共更新 {total_updated} 条Norm记录")

    # ---- 删除2021章节 ----
    print("\n--- 清理: 删除2021章节 ---")
    deleted = 0
    while True:
        leaves = conn.execute("""
            SELECT c.chap_ID FROM chapter c
            WHERE c.chap_ID >= 130000000 AND c.chap_ID < 200000000
            AND NOT EXISTS (SELECT 1 FROM chapter WHERE chap_PID=c.chap_ID)
            AND NOT EXISTS (SELECT 1 FROM Norm WHERE chap_ID=c.chap_ID)
        """).fetchall()
        if not leaves:
            break
        for (lid,) in leaves:
            conn.execute("DELETE FROM chapter WHERE chap_ID=?", (lid,))
            deleted += 1
        conn.commit()
    print(f"共删除 {deleted} 个2021章节")

    # ---- 验证 ----
    print("\n--- 验证 ---")
    remaining_ch = conn.execute(
        "SELECT COUNT(*) FROM chapter WHERE chap_ID >= 130000000 AND chap_ID < 200000000"
    ).fetchone()[0]
    orphan = conn.execute(
        "SELECT COUNT(*) FROM Norm WHERE chap_ID >= 130000000 AND chap_ID < 200000000"
    ).fetchone()[0]
    total_n = conn.execute("SELECT COUNT(*) FROM Norm").fetchone()[0]
    bj12 = conn.execute("SELECT COUNT(*) FROM Norm WHERE norm_Code LIKE 'BJ12.%'").fetchone()[0]
    bj21 = conn.execute("SELECT COUNT(*) FROM Norm WHERE norm_Code LIKE 'BJ21.%'").fetchone()[0]
    other = total_n - bj12 - bj21

    print(f"2021残留章节: {remaining_ch}")
    print(f"残留2021定额(orphan): {orphan}")
    print(f"Norm总数: {total_n}, BJ12: {bj12}, BJ21: {bj21}, 其他: {other}")

    # 迁移后各章定额分布
    print("\n--- 迁移后各章定额分布 ---")
    for root_id in sorted(set(A_MAP.values())):
        root = conn.execute("SELECT chap_Name, chap_code FROM chapter WHERE chap_ID=?", (root_id,)).fetchone()
        if not root:
            continue
        cnt = conn.execute("""
            SELECT COUNT(*) FROM Norm WHERE chap_ID IN (
                WITH RECURSIVE children(id) AS (
                    SELECT chap_ID FROM chapter WHERE chap_PID=?
                    UNION ALL
                    SELECT c.chap_ID FROM chapter c JOIN children ON c.chap_PID=children.id
                )
                SELECT id FROM children
                UNION ALL SELECT ?
            )
        """, (root_id, root_id)).fetchone()[0]
        print(f"  {root[1]} {root[0]}: {cnt}条")

    conn.close()
    print("\n完成!")

if __name__ == "__main__":
    main()
