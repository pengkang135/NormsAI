"""
Export matched norms consumption from UniqueBQ to 综合单价 sheet.
Multi-database: A册(建筑装饰) + B册(通用安装) + C册(市政园林).
Chapter grouping, per-subsection resources, SUMPRODUCT formulas.
"""
import json, sqlite3, re, shutil
from collections import defaultdict, Counter
from pathlib import Path

# ── Paths ──
DB_DIR = Path(r'F:\BaiduSyncdisk\2.清单定额\Norms-AI\db')
DB_PATHS = {
    'A': DB_DIR / '企业定额_A册_建筑装饰.sqlite',
    'B': DB_DIR / '企业定额_B册_通用安装.sqlite',
    'C': DB_DIR / '企业定额_C册_市政园林.sqlite',
}
BOQ_SRC = Path(r'f:\BaiduSyncdisk\5.报价\2026-7 ZooThailand\3报价书\BQ_Dusit_Zoo_Phase2_norms_fullcode_norms_v6.xlsx')
OUTPUT = Path(r'f:\BaiduSyncdisk\5.报价\2026-7 ZooThailand\3报价书\BQ_Dusit_Zoo_Phase2_norms_consumption.xlsx')

import fastexcel
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter

N_CONSUMPTION = 55
MAX_COL = 15 + N_CONSUMPTION
FIXED_COLS = 15
QTY_COL_START = FIXED_COLS + 1

EN_HEADERS = ["seq", "code", "item_name", "unit", "description", "type", "content", "rule",
              "english_name", "amount", "quantity", "rate", "labour", "materials", "mech"]
CN_HEADERS = ["序号", "定额编号", "项目名称", "单位", "项目特征", "分类指标", "工作内容", "计算规则",
              "英文名称", "成本合价", "工程量", "单价", "人工", "材料", "机械"]

# Fonts
FONT_NAME = '微软雅黑'
FONT_HDR = Font(name=FONT_NAME, size=9, bold=True)
FONT_HDR_EN = Font(name=FONT_NAME, size=8, bold=True)
FONT_CH = Font(name=FONT_NAME, size=9, bold=True, color='FFFFFF')
FONT_CH_EN = Font(name=FONT_NAME, size=9, bold=True, color='FFFFFF')
FONT_SEC = Font(name=FONT_NAME, size=9, bold=True, color='1A1A1A')
FONT_SUB = Font(name=FONT_NAME, size=9, bold=True, color='1A1A1A')
FONT_DATA = Font(name=FONT_NAME, size=9)
FONT_GRAY = Font(name=FONT_NAME, size=9, color='808080')
FONT_RES = Font(name=FONT_NAME, size=7)

FILL_HDR = PatternFill('solid', fgColor='FFD9E1F2')
FILL_CH = PatternFill('solid', fgColor='FF333F4F')
FILL_SEC = PatternFill('solid', fgColor='FFD9E1F2')
FILL_SUB = PatternFill('solid', fgColor='FFFBE5D6')

THIN = Border(left=Side('thin'), right=Side('thin'), top=Side('thin'), bottom=Side('thin'))


def classify_resource(kind_id, cons_name):
    ks = str(kind_id or 0)
    if ks.startswith('1') or '工日' in cons_name: return 'labour'
    if ks.startswith('3'): return 'mech'
    for kw in ['机','车','船','泵','钻','搅拌','起重','装载','推土','压路','打桩','挖掘','自卸','拖轮','驳','发电','空压','电焊']:
        if kw in cons_name: return 'mech'
    return 'materials'


def parse_boq_code(code):
    """Parse BOQ norm code like 'A.01.02.001.1-7' -> (volume, chapter_code, norm_code)."""
    parts = code.split('.')
    if len(parts) < 4:
        return None, None, None
    vol = parts[0]
    ch_code = '.'.join(parts[1:4])
    norm_code = '.'.join(parts[4:])
    return vol, ch_code, norm_code


def set_row_style(ws, row, font, fill=None, border=True):
    for ci in range(1, MAX_COL + 1):
        c = ws.cell(row, ci)
        c.font = font
        if fill: c.fill = fill
        if border: c.border = THIN


def get_chapter_hierarchy(cur, chap_id):
    """Walk up chapter hierarchy: returns [chapter, section, subsection, ...]."""
    chain = []
    current = chap_id
    while current and current != 0:
        cur.execute('SELECT chap_ID, chap_PID, chap_Name, chap_code FROM chapter WHERE chap_ID = ?', (current,))
        r = cur.fetchone()
        if not r: break
        chain.append({'id': r[0], 'pid': r[1], 'name': r[2], 'code': r[3]})
        current = r[1]
    chain.reverse()
    return chain


def main():
    # ── Step 1: Read UniqueBQ ──
    print("Reading UniqueBQ...")
    wb_in = fastexcel.read_excel(str(BOQ_SRC))
    df = wb_in.load_sheet_by_name('UniqueBQ').to_pandas()
    data = df.iloc[1:].copy()
    data.columns = ['Disc','Cat','Subcat','Desc','Unit','NC','NN','BQC','Qty','Rate','Total','_','NC2','NN2','U2','单价']

    # Build BOQ items with hierarchy
    boq_items = []
    for idx, row in data.iterrows():
        nc = str(row['NC']).strip()
        if not nc or nc in ('0', 'nan', '', '(空白)', 'Norm Code'):
            continue
        desc = str(row['Desc']).strip() if row['Desc'] else ''
        unit = str(row['Unit']).strip() if row['Unit'] else ''
        disc = str(row['Disc']).strip() if row['Disc'] else ''
        cat = str(row['Cat']).strip() if row['Cat'] else ''
        subcat = str(row['Subcat']).strip() if row['Subcat'] else ''
        boq_items.append({
            'boq_code': nc,
            'desc': desc,
            'unit': unit,
            'disc': disc,
            'cat': cat,
            'subcat': subcat,
        })

    # Deduplicate by norm code within same sub-discipline
    boq_dedup = []
    seen = set()
    for item in boq_items:
        key = (item['disc'], item['cat'], item['subcat'], item['boq_code'])
        if key not in seen:
            seen.add(key)
            boq_dedup.append(item)
    print(f"BOQ items: {len(boq_items)}, unique by sub-discipline: {len(boq_dedup)}")

    # ── Step 2: Parse & Group codes by database ──
    codes_by_db = defaultdict(list)
    parse_failures = []
    for item in boq_dedup:
        vol, ch_code, norm_code = parse_boq_code(item['boq_code'])
        if vol is None:
            parse_failures.append(item['boq_code'])
            continue
        item['volume'] = vol
        item['ch_code'] = ch_code
        item['norm_code'] = norm_code
        codes_by_db[vol].append(item)

    print(f"Parse failures: {len(parse_failures)}")
    for vol in sorted(codes_by_db.keys()):
        print(f"  {vol}册: {len(codes_by_db[vol])} items")
    if parse_failures:
        print(f"  Failed: {parse_failures[:5]}")

    # ── Step 3: Query each database ──
    norm_meta = {}
    cons_by_code = defaultdict(list)

    for vol, db_path in DB_PATHS.items():
        if not db_path.exists():
            print(f"  {vol}册 DB not found: {db_path}")
            continue
        items = codes_by_db.get(vol, [])
        if not items:
            continue

        print(f"\nQuerying {vol}册 ({len(items)} items)...")
        db = sqlite3.connect(str(db_path))
        cur = db.cursor()

        # Build chapter_code -> [chap_IDs with norms] mapping
        cur.execute("""
            SELECT DISTINCT c.chap_code, c.chap_ID
            FROM chapter c
            JOIN Norm n ON n.chap_ID = c.chap_ID
        """)
        ch_with_norms = defaultdict(list)
        for r in cur.fetchall():
            ch_with_norms[r[0]].append(r[1])

        # For each item, find matching norm
        matched_count = 0
        for item in items:
            ch_code = item['ch_code']
            norm_code = item['norm_code']
            chap_ids = ch_with_norms.get(ch_code, [])

            if not chap_ids:
                # Try matching without leading zeros or with different format
                continue

            found = False
            for cid in chap_ids:
                cur.execute(
                    'SELECT norm_ID, norm_Name, norm_Units, norm_BaseUnits FROM Norm WHERE chap_ID = ? AND norm_Code = ?',
                    (cid, norm_code))
                r = cur.fetchone()
                if r:
                    # Get hierarchy
                    chain = get_chapter_hierarchy(cur, cid)
                    chapter = chain[0]['name'] if len(chain) > 0 else ''
                    section = chain[1]['name'] if len(chain) > 1 else ''
                    subsect = chain[2]['name'] if len(chain) > 2 else ''
                    if len(chain) > 3:
                        subsect = chain[3]['name']

                    norm_id = r[0]
                    norm_meta[item['boq_code']] = {
                        'name': r[1], 'units': r[2], 'base_units': r[3],
                        'chapter': chapter, 'section': section, 'subchap': subsect,
                        'volume': vol, 'norm_id': norm_id
                    }

                    # Get consumption data
                    cur.execute("""
                        SELECT c2.cons_Code, c2.cons_Name, c2.cons_Units,
                               c2.cons_Price, ct.cont_Amount, c2.kind_ID
                        FROM Content ct
                        JOIN Consumption c2 ON ct.cons_ID = c2.cons_ID
                        WHERE ct.norm_ID = ?
                        ORDER BY c2.kind_ID, c2.cons_Code
                    """, (norm_id,))
                    for cr in cur.fetchall():
                        cls = classify_resource(cr[5], cr[1])
                        label = f"{cr[1]}\n{cr[2]}" if cr[2] else cr[1]
                        cons_by_code[item['boq_code']].append({
                            'name': cr[1], 'unit': cr[2], 'price': cr[3] or 0,
                            'amount': cr[4] or 0, 'cls': cls, 'label': label
                        })
                    found = True
                    matched_count += 1
                    break

            if not found:
                # Try searching across ALL chapters for the norm code
                cur.execute("""
                    SELECT n.norm_ID, n.norm_Name, n.norm_Units, n.norm_BaseUnits, n.chap_ID
                    FROM Norm n WHERE n.norm_Code = ?
                """, (norm_code,))
                rs = cur.fetchall()
                if rs:
                    for r2 in rs[:1]:
                        cid2 = r2[4]
                        chain = get_chapter_hierarchy(cur, cid2)
                        chapter = chain[0]['name'] if len(chain) > 0 else ''
                        section = chain[1]['name'] if len(chain) > 1 else ''
                        subsect = chain[2]['name'] if len(chain) > 2 else ''
                        if len(chain) > 3:
                            subsect = chain[3]['name']

                        norm_meta[item['boq_code']] = {
                            'name': r2[1], 'units': r2[2], 'base_units': r2[3],
                            'chapter': chapter, 'section': section, 'subchap': subsect,
                            'volume': vol, 'norm_id': r2[0]
                        }

                        cur.execute("""
                            SELECT c2.cons_Code, c2.cons_Name, c2.cons_Units,
                                   c2.cons_Price, ct.cont_Amount, c2.kind_ID
                            FROM Content ct
                            JOIN Consumption c2 ON ct.cons_ID = c2.cons_ID
                            WHERE ct.norm_ID = ?
                            ORDER BY c2.kind_ID, c2.cons_Code
                        """, (r2[0],))
                        for cr in cur.fetchall():
                            cls = classify_resource(cr[5], cr[1])
                            label = f"{cr[1]}\n{cr[2]}" if cr[2] else cr[1]
                            cons_by_code[item['boq_code']].append({
                                'name': cr[1], 'unit': cr[2], 'price': cr[3] or 0,
                                'amount': cr[4] or 0, 'cls': cls, 'label': label
                            })
                        matched_count += 1
                        break

        db.close()
        print(f"  Matched: {matched_count}/{len(items)}")

    total_matched = len(norm_meta)
    print(f"\nTotal matched norms: {total_matched}/{len(boq_dedup)}")

    if total_matched == 0:
        print("No norms matched! Aborting.")
        return

    # ── Step 4: Build chapter hierarchy ──
    chapters = {}
    for item in boq_dedup:
        code = item['boq_code']
        meta = norm_meta.get(code)
        if not meta:
            continue

        ch_full = meta.get('chapter', '')
        ch_key = meta.get('volume', '') + '.' + ch_full.split('.')[-1] if ch_full and '.' in ch_full else ch_full
        vol = meta.get('volume', 'A')
        sec = meta.get('section', '')
        sub = meta.get('subchap', '')

        # Use volume+chapter as grouping key
        group_key = f"{vol}|{ch_full}"
        if group_key not in chapters:
            ch_display = f"{vol}册 {ch_full}" if '册' not in ch_full else ch_full
            chapters[group_key] = {
                'cn': ch_display,
                'en': ch_full,
                'vol': vol,
                'sections': {}
            }

        sec_key = sec or '(未分类)'
        if sec_key not in chapters[group_key]['sections']:
            chapters[group_key]['sections'][sec_key] = {'subsections': {}}

        sub_key = sub or '(未分类)'
        if sub_key not in chapters[group_key]['sections'][sec_key]['subsections']:
            chapters[group_key]['sections'][sec_key]['subsections'][sub_key] = {
                'items': [], 'resources': [],
                'disc': item.get('disc', ''),
                'cat': item.get('cat', ''),
            }

        ss = chapters[group_key]['sections'][sec_key]['subsections'][sub_key]
        if not any(i['code'] == code for i in ss['items']):
            ss['items'].append({
                'code': code,
                'name': meta.get('name', item.get('desc', '')),
                'units': meta.get('units', item.get('unit', '')),
                'resources': cons_by_code.get(code, [])
            })
            existing = {r2['label'] for r2 in ss['resources']}
            for res in cons_by_code.get(code, []):
                if res['label'] not in existing:
                    existing.add(res['label'])
                    ss['resources'].append(res)

    # Sort resources per subsection: labour -> materials -> mech
    cls_order = {'labour': 0, 'materials': 1, 'mech': 2}
    for ch_d in chapters.values():
        for sec_d in ch_d['sections'].values():
            for sub_d in sec_d['subsections'].values():
                sub_d['resources'].sort(key=lambda x: cls_order.get(x['cls'], 9))

    # ── Step 5: Write Excel ──
    print("\nCreating Excel output...")
    wb = Workbook()
    ws = wb.active
    ws.title = '综合单价'

    # Row 1-2: headers
    for ci, h in enumerate(EN_HEADERS, 1):
        c = ws.cell(1, ci, value=h)
        c.font = FONT_HDR; c.fill = FILL_HDR; c.border = THIN
        c.alignment = Alignment(wrap_text=True, horizontal='center', vertical='center')
    for ci in range(QTY_COL_START, MAX_COL + 1):
        c = ws.cell(1, ci, value=f"qty{ci - FIXED_COLS}")
        c.font = FONT_HDR_EN; c.fill = FILL_HDR; c.border = THIN

    for ci, h in enumerate(CN_HEADERS, 1):
        c = ws.cell(2, ci, value=h)
        c.font = FONT_HDR; c.fill = FILL_HDR; c.border = THIN
        c.alignment = Alignment(wrap_text=True, horizontal='center', vertical='center')
    for ci in range(QTY_COL_START, MAX_COL + 1):
        c = ws.cell(2, ci, value=f"消耗量{ci - FIXED_COLS}")
        c.font = FONT_HDR_EN; c.fill = FILL_HDR; c.border = THIN

    # Chapter ordering: A.01-A.24, B.03-B.14, C.20-C.33
    def ch_sort_key(ch_key):
        parts = ch_key.split('|')
        if len(parts) < 2: return (99, 99)
        vol = parts[0]
        try:
            ch_num = int(re.search(r'(\d+)', parts[1]).group(1)) if re.search(r'(\d+)', parts[1]) else 99
        except:
            ch_num = 99
        vol_order = {'A': 0, 'B': 1, 'C': 2}
        return (vol_order.get(vol, 99), ch_num)

    ordered_ch = sorted(chapters.items(), key=lambda x: ch_sort_key(x[0]))

    row = 3
    seq = 1

    for ch_key, ch_data in ordered_ch:
        # Chapter header
        ws.cell(row, 2, value=ch_key).font = FONT_CH
        ws.cell(row, 3, value=f"【{ch_data['cn']}】").font = FONT_CH
        ws.cell(row, 9, value=f"【{ch_data['en']}】").font = FONT_CH_EN
        set_row_style(ws, row, FONT_CH, FILL_CH)
        row += 1

        for sec_name, sec_data in ch_data['sections'].items():
            # Section header
            ws.cell(row, 3, value=f"《{sec_name}》").font = FONT_SEC
            set_row_style(ws, row, FONT_SEC, FILL_SEC)
            ws.row_dimensions[row].outline_level = 1
            row += 1

            for sub_name, sub_data in sec_data['subsections'].items():
                if not sub_data['items']:
                    continue

                resources = sub_data['resources']
                n_res = min(len(resources), N_CONSUMPTION)
                resources = resources[:n_res]

                labour_cols = []; material_cols = []; mech_cols = []
                for ri, res in enumerate(resources):
                    col = QTY_COL_START + ri
                    if res['cls'] == 'labour': labour_cols.append(col)
                    elif res['cls'] == 'materials': material_cols.append(col)
                    elif res['cls'] == 'mech': mech_cols.append(col)

                # Subsection header with resource headers
                ws.cell(row, 3, value=f"{{{sub_name}}}").font = FONT_SUB
                for ri, res in enumerate(resources):
                    col = QTY_COL_START + ri
                    c = ws.cell(row, col, value=res['label'])
                    c.font = FONT_RES
                    c.alignment = Alignment(wrap_text=True, vertical='center')
                set_row_style(ws, row, FONT_SUB, FILL_SUB)
                ws.row_dimensions[row].outline_level = 2
                row += 1

                # Price row
                price_row = row
                ws.cell(row, 3, value="参考单价 ->").font = FONT_GRAY
                for ri in range(n_res):
                    ws.cell(row, QTY_COL_START + ri).number_format = "#,##0.00"
                set_row_style(ws, row, FONT_GRAY, None)
                ws.row_dimensions[row].outline_level = 2
                row += 1

                # Data rows
                for item in sub_data['items']:
                    data_row = row
                    ws.cell(row, 1, value=seq).font = FONT_DATA
                    ws.cell(row, 1).number_format = "0"
                    ws.cell(row, 1).alignment = Alignment(horizontal='center')
                    ws.cell(row, 2, value=item['code']).number_format = "@"
                    ws.cell(row, 2).font = FONT_DATA
                    ws.cell(row, 3, value=item['name']).font = FONT_DATA
                    ws.cell(row, 4, value=item['units']).font = FONT_DATA
                    ws.cell(row, 6, value=sub_name).font = FONT_DATA
                    ws.cell(row, 7, value="详见定额原文").font = FONT_DATA
                    ws.cell(row, 8, value="按设计图示尺寸计算").font = FONT_DATA

                    res_map = {r2['label']: r2['amount'] for r2 in item['resources']}
                    for ri, res in enumerate(resources):
                        col = QTY_COL_START + ri
                        val = res_map.get(res['label'])
                        if val is not None:
                            ws.cell(row, col, value=val).number_format = "#,##0.0000"
                            ws.cell(row, col).font = FONT_DATA

                    # K(11) → rate = M+N+O
                    ws.cell(row, 12, value=f"=M{data_row}+N{data_row}+O{data_row}").number_format = "#,##0.00"
                    ws.cell(row, 12).font = FONT_DATA

                    # L(12) → labour SUMPRODUCT
                    if labour_cols:
                        cl = f"{get_column_letter(labour_cols[0])}{price_row}:{get_column_letter(labour_cols[-1])}{price_row}"
                        ql = f"{get_column_letter(labour_cols[0])}{data_row}:{get_column_letter(labour_cols[-1])}{data_row}"
                        ws.cell(row, 13, value=f"=SUMPRODUCT({cl},{ql})").number_format = "#,##0.00"
                        ws.cell(row, 13).font = FONT_DATA

                    # M(13) → materials SUMPRODUCT
                    if material_cols:
                        cm = f"{get_column_letter(material_cols[0])}{price_row}:{get_column_letter(material_cols[-1])}{price_row}"
                        qm = f"{get_column_letter(material_cols[0])}{data_row}:{get_column_letter(material_cols[-1])}{data_row}"
                        ws.cell(row, 14, value=f"=SUMPRODUCT({cm},{qm})").number_format = "#,##0.00"
                        ws.cell(row, 14).font = FONT_DATA

                    # N(14) → mech SUMPRODUCT
                    if mech_cols:
                        cn = f"{get_column_letter(mech_cols[0])}{price_row}:{get_column_letter(mech_cols[-1])}{price_row}"
                        qn = f"{get_column_letter(mech_cols[0])}{data_row}:{get_column_letter(mech_cols[-1])}{data_row}"
                        ws.cell(row, 15, value=f"=SUMPRODUCT({cn},{qn})").number_format = "#,##0.00"
                        ws.cell(row, 15).font = FONT_DATA

                    for ci in range(1, MAX_COL + 1):
                        ws.cell(row, ci).border = THIN
                    ws.row_dimensions[row].outline_level = 3
                    row += 1; seq += 1

                row += 1  # blank between subsections
            row += 1  # blank between sections
        row += 1  # blank between chapters

    # Column widths
    for cl, w in {"A": 6, "B": 22, "C": 36, "D": 10, "E": 14, "F": 14, "G": 18, "H": 16, "I": 18}.items():
        ws.column_dimensions[cl].width = w
    for ci in range(10, FIXED_COLS + 1):
        ws.column_dimensions[get_column_letter(ci)].width = 12
    for ci in range(QTY_COL_START, MAX_COL + 1):
        ws.column_dimensions[get_column_letter(ci)].width = 13

    ws.freeze_panes = "D3"
    ws.sheet_properties.outlinePr.summaryBelow = False

    print(f"Saving... ({row} rows, {seq-1} data rows)")
    wb.save(str(OUTPUT))
    print(f"Done! Written to {OUTPUT}")


if __name__ == '__main__':
    main()
