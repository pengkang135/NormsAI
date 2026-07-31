def render(page_data):
    lines = page_data.get("lines", [])

    y_groups = {}
    y_keys = []
    for line in lines:
        y = line["y"]
        matched = None
        for yk in y_keys:
            if abs(y - yk) <= 3:
                matched = yk
                break
        if matched is not None:
            y_groups[matched].append(line)
        else:
            y_keys.append(y)
            y_groups[y] = [line]

    def _col(x):
        if x < 200:
            return "category"
        elif x < 380:
            return "depth"
        else:
            return "coeff"

    title_text = ""
    header = {"category": "", "depth": "", "coeff": ""}
    data_rows = []
    note_text = ""
    page_num = ""

    for y in sorted(y_keys):
        group = y_groups[y]
        avg_y = y

        if 280 < avg_y < 300:
            title_text = group[0]["text"]
        elif 300 < avg_y < 316:
            for line in group:
                header[_col(line["x"])] = line["text"]
        elif 316 < avg_y < 370:
            row = {"category": "", "depth": "", "coeff": ""}
            for line in group:
                row[_col(line["x"])] = line["text"]
            data_rows.append((avg_y, row))
        elif 370 < avg_y < 390:
            note_text = group[0]["text"]
        elif 390 < avg_y < 400:
            page_num = group[0]["text"]

    data_rows.sort(key=lambda r: r[0])

    rows = []
    for _, row in data_rows:
        rows.append(
            '<tr>'
            '<td style="text-align:center;padding:6px 8px;border:1px solid #333;font-size:14px;">%s</td>'
            '<td style="text-align:center;padding:6px 8px;border:1px solid #333;font-size:14px;">%s</td>'
            '<td style="text-align:center;padding:6px 8px;border:1px solid #333;font-size:14px;">%s</td>'
            '</tr>' % (row["category"], row["depth"], row["coeff"])
        )

    html = (
        '<div style="margin:16px 0;font-family:SimSun,宋体,serif;">'
        '<p style="text-align:center;font-size:16px;font-weight:bold;margin:0 0 10px 0;">%s</p>'
        '<table style="border-collapse:collapse;width:100%%;font-size:14px;">'
        '<thead>'
        '<tr>'
        '<th style="border:1px solid #333;padding:6px 8px;background:#e8e4d8;font-size:15px;width:20%%;">%s</th>'
        '<th style="border:1px solid #333;padding:6px 8px;background:#e8e4d8;font-size:15px;width:40%%;">%s</th>'
        '<th style="border:1px solid #333;padding:6px 8px;background:#e8e4d8;font-size:15px;width:40%%;">%s</th>'
        '</tr>'
        '</thead>'
        '<tbody>'
        '%s'
        '</tbody>'
        '<tfoot>'
        '<tr>'
        '<td colspan="3" style="border:1px solid #333;padding:6px 12px;background:#f5f5f5;font-size:13px;color:#555;text-align:left;">%s</td>'
        '</tr>'
        '</tfoot>'
        '</table>'
        '</div>'
    ) % (
        title_text,
        header["category"], header["depth"], header["coeff"],
        "\n".join(rows),
        note_text,
    )

    return html
