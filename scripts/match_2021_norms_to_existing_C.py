"""
C册: 2021定额逐条匹配到现有叶章节 (直接版 v3)。

逐个norm判断是否需要重新分布，然后匹配。
"""
import sqlite3, shutil, time, re
from pathlib import Path
from difflib import SequenceMatcher
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "db"
C_DB = DB_DIR / "企业定额_C册_市政园林.sqlite"

C_MAP = {
    170000000: 1000000, 180000000: 2000000, 190000000: 3000000,
    231000000: 4000000, 232000000: 4000000, 233000000: 4000000,
    234000000: 4000000, 235000000: 4000000, 236000000: 4000000,
    310000000: 4000000, 380000000: 6000000,
    841000000: 20000000, 842000000: 20000000,
    843000000: 21000000, 844000000: 22000000, 845000000: 33000000,
}

UNIT_RE = re.compile(r'\s*(m[²³23]?|kg|t|mm|cm|m|km|个|套|座|根|块|片|条|台|组|项|元|%|‰)\s*$', re.IGNORECASE)
PAREN_RE = re.compile(r'[（(][^)）]*[)）]$')
CODE_RE = re.compile(r'^[A-Za-z](\\.\\d+)+[\\s]+')
CN_PREFIX = re.compile(r'^[一二三四五六七八九十]+[、．.\\s)]*')

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
        if cur in C_MAP:
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
            result.append((cid, cname, ccode))
    return result

def build_norm_index(conn, leaf_chapters):
    index = {}
    for cid, _, _ in leaf_chapters:
        norms = conn.execute("SELECT norm_Name FROM Norm WHERE chap_ID=?", (cid,)).fetchall()
        index[cid] = [clean_name(n[0]) for n in norms]
    return index

def match_score(norm_name, target_name):
    a = clean_name(norm_name)
    b = clean_name(target_name)
    score = SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:
        score = max(score, 0.85)
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
    print("C册: 2021定额逐条匹配到现有叶章节 (直接版 v3)")
    print("=" * 70)

    bak = backup_db(C_DB)
    print("[BACKUP] %s" % bak.name)

    conn = sqlite3.connect(str(C_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # 预加载各域叶章节
    domain_leaves = {}
    domain_norm_index = {}
    for k2021, k_existing in C_MAP.items():
        if k_existing not in domain_leaves:
            leaves = get_domain_leaves(conn, k_existing)
            domain_leaves[k_existing] = leaves
            domain_norm_index[k_existing] = build_norm_index(conn, leaves)
    total_leaves = sum(len(v) for v in domain_leaves.values())
    print("域内现有叶章节总数: %d" % total_leaves)

    # 获取所有BJ21定额，含父章节名
    all_bj21 = conn.execute("""
        SELECT n.norm_ID, n.norm_Code, n.norm_Name, n.chap_ID, c.chap_Name,
               (SELECT chap_Name FROM chapter WHERE chap_ID=c.chap_PID) as parent_name
        FROM Norm n JOIN chapter c ON c.chap_ID = n.chap_ID
        WHERE n.norm_Code LIKE 'BJ21.%'
    """).fetchall()
    print("BJ21定额总数: %d" % len(all_bj21))

    # 分离: 需要重新分布的 vs 已在现有章节下的
    to_redistribute = []
    already_placed = []
    for norm in all_bj21:
        mk = find_map_key(conn, norm['chap_ID'])
        if mk is not None and mk in C_MAP:
            to_redistribute.append(norm)
        else:
            already_placed.append(norm)

    print("已在现有章节下: %d" % len(already_placed))
    print("需要重新分布: %d" % len(to_redistribute))

    if not to_redistribute:
        print("\n无需重新分布，所有BJ21定额已在正确位置。")
        conn.close()
        return

    # 为每个目标域标记是否有现有定额
    domain_has_norms = {}
    for k_existing, leaves in domain_leaves.items():
        idx = domain_norm_index.get(k_existing, {})
        domain_has_norms[k_existing] = any(len(v) > 0 for v in idx.values())

    # 逐条匹配
    norm_mapping = {}
    no_match = []
    stats = {"high": 0, "mid": 0, "low": 0}

    for norm in to_redistribute:
        nid = norm['norm_ID']
        ncode = norm['norm_Code']
        nname = norm['norm_Name']
        chap_id = norm['chap_ID']
        parent_name = norm['parent_name'] or ''

        mk = find_map_key(conn, chap_id)
        target_root = C_MAP.get(mk)
        if target_root is None or target_root not in domain_leaves:
            continue

        leaves = domain_leaves[target_root]
        norm_index = domain_norm_index[target_root]
        has_existing = domain_has_norms.get(target_root, False)

        best_cid, best_score = None, 0
        pname = clean_name(parent_name)

        for cid, cname, _ in leaves:
            # 匹配现有叶章节名
            s = match_score(nname, scode(cname))
            if s > best_score:
                best_score = s
                best_cid = cid

            # 匹配该章节下现有定额名
            for ename in norm_index.get(cid, []):
                s = match_score(nname, ename)
                if s > best_score:
                    best_score = s
                    best_cid = cid

            # 用父章节名匹配现有叶章节名（对无现有定额的域尤为重要）
            if pname:
                s = match_score(pname, scode(cname))
                if s > best_score:
                    best_score = s
                    best_cid = cid

            # 父章节名 + 定额名组合匹配
            if pname:
                s = match_score(pname + " " + nname, scode(cname))
                if s > best_score:
                    best_score = s
                    best_cid = cid

        if best_cid:
            norm_mapping[nid] = (best_cid, best_score)
            if best_score >= 0.85:
                stats["high"] += 1
            elif best_score >= 0.6:
                stats["mid"] += 1
            else:
                stats["low"] += 1
        else:
            if leaves:
                norm_mapping[nid] = (leaves[0][0], 0.0)
                stats["low"] += 1
            else:
                no_match.append((nid, ncode, nname))

    total_mapped = len(norm_mapping)
    print("\n匹配结果:")
    print("  高分(>=0.85): %d (%.1f%%)" % (stats["high"], 100.0*stats["high"]/len(to_redistribute)))
    print("  中分(0.6-0.85): %d (%.1f%%)" % (stats["mid"], 100.0*stats["mid"]/len(to_redistribute)))
    print("  低分(<0.6): %d (%.1f%%)" % (stats["low"], 100.0*stats["low"]/len(to_redistribute)))
    print("  总计: %d / %d" % (total_mapped, len(to_redistribute)))
    if no_match:
        print("  完全无匹配(无域叶章节): %d" % len(no_match))

    # 样例
    if stats["high"] > 0:
        high_list = [(nid, cid, s) for nid, (cid, s) in norm_mapping.items() if s >= 0.85]
        print("\n--- 高分匹配样例 (前10条) ---")
        for i, (nid, cid, score) in enumerate(high_list[:10]):
            nr = conn.execute("SELECT norm_Code, norm_Name FROM Norm WHERE norm_ID=?", (nid,)).fetchone()
            ch = conn.execute("SELECT chap_Name FROM chapter WHERE chap_ID=?", (cid,)).fetchone()
            print("  %s '%s' -> %s" % (nr[0], nr[1], ch[0] if ch else '???'))

    # ---- 逐条更新 ----
    print("\n--- 迁移: 逐条更新Norm.chap_ID ---")
    by_target = defaultdict(list)
    for nid, (target_cid, _) in norm_mapping.items():
        by_target[target_cid].append(nid)

    total_updated = 0
    for target_cid, nid_list in by_target.items():
        placeholders = ','.join('?' * len(nid_list))
        n = conn.execute(
            "UPDATE Norm SET chap_ID=? WHERE norm_ID IN (" + placeholders + ")",
            [target_cid] + nid_list
        ).rowcount
        total_updated += n
    conn.commit()
    print("共更新 %d 条Norm记录" % total_updated)

    # ---- 删除空章节 ----
    print("\n--- 清理: 删除空章节 ---")
    deleted = 0
    while True:
        leaves = conn.execute("""
            SELECT c.chap_ID FROM chapter c
            WHERE c.chap_PID != 0
            AND NOT EXISTS (SELECT 1 FROM chapter WHERE chap_PID=c.chap_ID)
            AND NOT EXISTS (SELECT 1 FROM Norm WHERE chap_ID=c.chap_ID)
        """).fetchall()
        if not leaves:
            break
        for (lid,) in leaves:
            conn.execute("DELETE FROM chapter WHERE chap_ID=?", (lid,))
            deleted += 1
        conn.commit()
    print("共删除 %d 个空章节" % deleted)

    # 删除空的2021根章节
    for rid in [160000000, 200100000, 230000000, 300000000, 370000000, 840000000]:
        children = conn.execute("SELECT COUNT(*) FROM chapter WHERE chap_PID=?", (rid,)).fetchone()[0]
        norms = conn.execute("SELECT COUNT(*) FROM Norm WHERE chap_ID=?", (rid,)).fetchone()[0]
        if children == 0 and norms == 0:
            conn.execute("DELETE FROM chapter WHERE chap_ID=?", (rid,))
            print("  删除空根章节: %d" % rid)

    conn.commit()

    # ---- 验证 ----
    print("\n--- 验证 ---")
    remaining = 0
    for norm in conn.execute("SELECT norm_ID, chap_ID FROM Norm WHERE norm_Code LIKE 'BJ21.%'").fetchall():
        mk = find_map_key(conn, norm['chap_ID'])
        if mk is not None and mk in C_MAP:
            remaining += 1

    total_n = conn.execute("SELECT COUNT(*) FROM Norm").fetchone()[0]
    bj12 = conn.execute("SELECT COUNT(*) FROM Norm WHERE norm_Code LIKE 'BJ12.%'").fetchone()[0]
    bj21 = conn.execute("SELECT COUNT(*) FROM Norm WHERE norm_Code LIKE 'BJ21.%'").fetchone()[0]
    roots = conn.execute("SELECT COUNT(*) FROM chapter WHERE chap_PID=0").fetchone()[0]

    print("残留2021子树定额: %d" % remaining)
    print("Norm总数: %d, BJ12: %d, BJ21: %d" % (total_n, bj12, bj21))
    print("根章节数: %d" % roots)

    conn.close()
    print("\n完成!")

if __name__ == "__main__":
    main()
