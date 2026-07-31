def render(page_data_37, page_data_38=None, page_data_39=None, page_data_40=None, page_data_41=None):
    pages = [p for p in [page_data_37, page_data_38, page_data_39, page_data_40, page_data_41] if p is not None]
    if not pages:
        return ""

    lines = _collect_data_lines(pages)
    levels = _extract_levels(lines)

    return _build_html(levels)


def _collect_data_lines(pages):
    HEADER_Y_MAX = [155, 145, 145, 135, 120]
    lines = []
    for p_idx, page in enumerate(pages):
        header_y = HEADER_Y_MAX[min(p_idx, len(HEADER_Y_MAX) - 1)]
        for ln in page.get("lines", []):
            text = ln["text"].strip()
            if not text:
                continue
            if text.startswith("-") and text.endswith("-") and len(text) < 8:
                continue
            if ln["y"] < header_y:
                continue
            lines.append({"x": ln["x"], "y": ln["y"], "text": text, "page": p_idx})
    lines.sort(key=lambda l: (l["page"], l["y"], l["x"]))
    return lines


def _classify_kind(x, t):
    if 55 <= x < 185:
        return "rock"
    if 185 <= x < 250:
        return "density"
    if 250 <= x < 315:
        return "drill_alloy"
    if 315 <= x < 400:
        return "drill_quenched"
    if 400 <= x < 465:
        return "drill_manual"
    if 465 <= x < 515:
        return "strength"
    if 515 <= x < 560:
        return "coefficient"
    return "other"


def _is_new_rock_start(t):
    import re
    return bool(re.match(r'^\d+\.\s', t))


def _is_parenthetical(t):
    return t.startswith("(") or t.startswith("（")


def _is_level_marker(t):
    return t in {"V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV", "XVI"}


def _extract_levels(lines):
    levels = []
    current_rocks = []
    current_values = {}
    current_alts = {}
    current_level_name = None
    pending_rock = None

    COL_KEYS = ["drill_alloy", "drill_quenched", "drill_manual", "strength", "coefficient"]

    def _save_level():
        nonlocal current_level_name, current_rocks, current_values, current_alts, pending_rock
        if pending_rock is not None:
            current_rocks.append(pending_rock)
            pending_rock = None
        if current_rocks or current_level_name:
            levels.append({
                "level": current_level_name or "?",
                "rocks": current_rocks,
                "values": current_values,
                "alt_values": current_alts,
            })
        current_level_name = None
        current_rocks = []
        current_values = {}
        current_alts = {}

    for ln in lines:
        x, y, t = ln["x"], ln["y"], ln["text"]
        kind = _classify_kind(x, t)

        if x < 50 and _is_level_marker(t):
            current_level_name = t
            continue

        if kind == "rock":
            is_new_rock = _is_new_rock_start(t)
            is_level_start = is_new_rock and t.startswith("1.")

            if is_level_start:
                if current_level_name is not None and current_rocks:
                    _save_level()
                if pending_rock is not None:
                    current_rocks.append(pending_rock)
                pending_rock = {"name": t, "density": None}

            elif is_new_rock:
                if pending_rock is not None:
                    current_rocks.append(pending_rock)
                pending_rock = {"name": t, "density": None}

            else:
                if pending_rock is not None:
                    pending_rock["name"] += t
                elif current_rocks:
                    current_rocks[-1]["name"] += t

        elif kind == "density":
            val = t
            if pending_rock is not None:
                if pending_rock["density"] is None:
                    pending_rock["density"] = val
            elif current_rocks:
                if current_rocks[-1]["density"] is None:
                    current_rocks[-1]["density"] = val

        elif kind in COL_KEYS:
            if _is_parenthetical(t):
                if kind not in current_alts:
                    current_alts[kind] = t
            else:
                if kind not in current_values:
                    current_values[kind] = t

        elif kind == "other":
            pass

    _save_level()

    prev_vals = {}
    for lv in levels:
        vals = lv["values"]
        for k in COL_KEYS:
            if k not in vals and k in prev_vals:
                vals[k] = prev_vals[k]
        alt = lv["alt_values"]
        for k in COL_KEYS:
            if k not in alt and k in vals:
                alt[k] = vals[k]
        prev_vals = {k: vals.get(k, "") for k in COL_KEYS}

    return levels


def _build_html(levels):
    css = """<style>
.app2-table { border-collapse: collapse; width: 100%; font-family: "SimSun","宋体",serif; font-size: 14px; }
.app2-table th,.app2-table td { border: 1px solid #555; padding: 5px 6px; text-align: center; vertical-align: middle; }
.app2-table thead th { background: #2c3e50; color: #fff; font-weight: bold; font-size: 15px; }
.app2-table .hdr-sub { background: #3d566e; color: #fff; font-size: 13px; font-weight: normal; }
.app2-table .hdr-detail { background: #4a6d8c; color: #eee; font-size: 12px; font-weight: normal; }
.app2-table .hdr-title { background: #1a252f; color: #fff; font-size: 17px; letter-spacing: 4px; }
.app2-table td.col-lv { width: 5%; font-weight: bold; font-size: 15px; background: #dce3e8; }
.app2-table td.col-name { width: 28%; text-align: left; padding-left: 8px; }
.app2-table td.col-density { width: 9%; }
.app2-table td.col-da, .app2-table td.col-dq, .app2-table td.col-dm { width: 11%; }
.app2-table td.col-strength { width: 10%; }
.app2-table td.col-coeff { width: 7%; }
.app2-table tr.lv-sep td { border-top: 2.5px solid #1a252f; }
.app2-table tr.alt-row td { background: #f7f4ed; font-size: 12px; color: #888; font-style: italic; }
.app2-table tr.alt-row td.col-lv { background: #efebe0; }
</style>"""

    html = css
    html += '<table class="app2-table">'
    html += '<thead>'
    html += '<tr><th class="hdr-title" colspan="8">附表2 &nbsp; 岩石分级表</th></tr>'
    html += '<tr><th class="hdr-sub" colspan="3"></th><th class="hdr-sub" colspan="4">净钻时间（min/m）</th><th class="hdr-sub" colspan="1"></th></tr>'
    html += '<tr>'
    html += '<th class="hdr-detail" rowspan="2">级别</th>'
    html += '<th class="hdr-detail" rowspan="2">岩 石 名 称</th>'
    html += '<th class="hdr-detail" rowspan="2">平均容重<br>(kg/m&sup3;)</th>'
    html += '<th class="hdr-detail" colspan="1">用&phi;30mm<br>合金钻头</th>'
    html += '<th class="hdr-detail" colspan="1">用&phi;30mm<br>淬火钻头</th>'
    html += '<th class="hdr-detail" colspan="1">用&phi;25mm<br>钻杆</th>'
    html += '<th class="hdr-detail" rowspan="2">极限抗压强度<br>(MPa)</th>'
    html += '<th class="hdr-detail" rowspan="2">系数<br>f</th>'
    html += '</tr>'
    html += '<tr>'
    html += '<th class="hdr-detail">凿岩机打眼<br>(工作气压4.5标准大气压)</th>'
    html += '<th class="hdr-detail">凿岩机打眼<br>(工作气压4.5标准大气压)</th>'
    html += '<th class="hdr-detail">人工单人打眼</th>'
    html += '</tr>'
    html += '</thead>'
    html += '<tbody>'

    for lv_idx, lv in enumerate(levels):
        level_name = lv["level"]
        rocks = lv["rocks"]
        vals = lv.get("values", {})
        alt = lv.get("alt_values", {})

        drill_alloy = vals.get("drill_alloy", "")
        drill_quenched = vals.get("drill_quenched", "")
        drill_manual = vals.get("drill_manual", "")
        strength = vals.get("strength", "")
        coefficient = vals.get("coefficient", "")

        alt_drill_alloy = alt.get("drill_alloy", "")
        alt_drill_quenched = alt.get("drill_quenched", "")
        alt_drill_manual = alt.get("drill_manual", "")
        alt_strength = alt.get("strength", "")
        alt_coefficient = alt.get("coefficient", "")

        sep_class = ' class="lv-sep"' if lv_idx > 0 else ""

        n_rows = len(rocks) if rocks else 1

        if rocks:
            first = rocks[0]
            html += '<tr{}>'.format(sep_class)
            html += '<td class="col-lv" rowspan="{}">{}</td>'.format(n_rows, level_name)
            html += '<td class="col-name">{}</td>'.format(_esc(first["name"]))
            html += '<td class="col-density">{}</td>'.format(_esc(first.get("density") or ""))
            html += '<td class="col-da" rowspan="{}">{}</td>'.format(n_rows, _esc(drill_alloy))
            html += '<td class="col-dq" rowspan="{}">{}</td>'.format(n_rows, _esc(drill_quenched))
            html += '<td class="col-dm" rowspan="{}">{}</td>'.format(n_rows, _esc(drill_manual))
            html += '<td class="col-strength" rowspan="{}">{}</td>'.format(n_rows, _esc(strength))
            html += '<td class="col-coeff" rowspan="{}">{}</td>'.format(n_rows, _esc(coefficient))
            html += '</tr>'

            for r in rocks[1:]:
                html += '<tr>'
                html += '<td class="col-name">{}</td>'.format(_esc(r["name"]))
                html += '<td class="col-density">{}</td>'.format(_esc(r.get("density") or ""))
                html += '</tr>'
        else:
            html += '<tr{}>'.format(sep_class)
            html += '<td class="col-lv">{}</td>'.format(level_name)
            html += '<td class="col-name"></td>'
            html += '<td class="col-density"></td>'
            html += '<td class="col-da">{}</td>'.format(_esc(drill_alloy))
            html += '<td class="col-dq">{}</td>'.format(_esc(drill_quenched))
            html += '<td class="col-dm">{}</td>'.format(_esc(drill_manual))
            html += '<td class="col-strength">{}</td>'.format(_esc(strength))
            html += '<td class="col-coeff">{}</td>'.format(_esc(coefficient))
            html += '</tr>'

        alt_vals_list = [alt_drill_alloy, alt_drill_quenched, alt_drill_manual, alt_strength, alt_coefficient]
        main_vals_list = [drill_alloy, drill_quenched, drill_manual, strength, coefficient]
        has_alt = any(v and (v != m) for v, m in zip(alt_vals_list, main_vals_list))
        if has_alt:
            html += '<tr class="alt-row">'
            html += '<td class="col-lv"></td>'
            html += '<td class="col-name" style="text-align:right;padding-right:8px;">备选值:</td>'
            html += '<td class="col-density"></td>'
            html += '<td class="col-da">{}</td>'.format(_esc(alt_drill_alloy))
            html += '<td class="col-dq">{}</td>'.format(_esc(alt_drill_quenched))
            html += '<td class="col-dm">{}</td>'.format(_esc(alt_drill_manual))
            html += '<td class="col-strength">{}</td>'.format(_esc(alt_strength))
            html += '<td class="col-coeff">{}</td>'.format(_esc(alt_coefficient))
            html += '</tr>'

    html += '</tbody>'
    html += '</table>'
    return html


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
