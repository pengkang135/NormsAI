"""OCR utilities extracted from norms_agent."""
import re, numpy as np
from PIL import Image, ImageEnhance
def _cluster_1d(vals, tol):
    if not vals: return []
    sv = sorted(vals); clusters = [[sv[0]]]
    for v in sv[1:]:
        if v - clusters[-1][-1] <= tol: clusters[-1].append(v)
        else: clusters.append([v])
    return [sum(c)/len(c) for c in clusters]


def _iou(b1, b2):
    x1,y1 = max(b1["x1"],b2["x1"]), max(b1["y1"],b2["y1"])
    x2,y2 = min(b1["x2"],b2["x2"]), min(b1["y2"],b2["y2"])
    inter = max(0,x2-x1)*max(0,y2-y1)
    a1 = (b1["x2"]-b1["x1"])*(b1["y2"]-b1["y1"])
    a2 = (b2["x2"]-b2["x1"])*(b2["y2"]-b2["y1"])
    return inter/(a1+a2-inter+1e-6)


def _fix(txt):
    if not txt: return txt
    txt = txt.replace("冻士","冻土").replace("毎","每")
    for a,u in ROMAN_MAP: txt = txt.replace(a,u)
    # Fix 般土方→一般土方, but NOT when preceded by 一 (avoid "一一般")
    txt = re.sub(r'(?<!一)般土方', '一般土方', txt)
    return txt


def _skip(txt):
    if not txt: return True
    if txt in SKIP_TEXTS: return True
    if txt.startswith('.') and len(txt)<=2: return True
    return False


def _clean_title(t):
    return re.sub(r'^[一二三四五六七八九十]+[、，]\s*','',t)


def ocr_multi_pass(page_img, ocr_engine):
    all_blocks = []
    for scale, enhance in [(2,1.0),(3,1.0),(2,1.5)]:
        if enhance != 1.0: arr = np.array(ImageEnhance.Contrast(page_img).enhance(enhance))
        else:
            w,h = page_img.size
            arr = np.array(page_img.resize((int(w*scale/2),int(h*scale/2)),Image.LANCZOS))
        result, _ = ocr_engine(arr)
        if result:
            sx = 2.0/scale
            for box,text,conf in result:
                if float(conf)<0.3: continue
                all_blocks.append({"x1":float(box[0][0])*sx,"y1":float(box[0][1])*sx,
                    "x2":float(box[2][0])*sx,"y2":float(box[2][1])*sx,
                    "text":text.strip(),"confidence":float(conf)})
    deduped = []
    for b in sorted(all_blocks, key=lambda x:(-x["confidence"],-len(x["text"]))):
        dup = next((d for d in deduped if _iou(b,d)>0.5),None)
        if dup:
            if len(b["text"])>len(dup["text"]): dup.update(b)
        else: deduped.append(b)
    deduped.sort(key=lambda b:(b["y1"],b["x1"]))
    return deduped


def build_grid(blocks):
    yc = [(b["y1"]+b["y2"])/2 for b in blocks]; row_ys = _cluster_1d(yc,12)
    qx = sorted([(b["x1"]+b["x2"])/2 for b in blocks if re.match(r'^\d{4}$',b["text"])])
    xc = [(b["x1"]+b["x2"])/2 for b in blocks]; all_cols = _cluster_1d(xc,25)
    col_xs = [x for x in all_cols if x<qx[0]-30]+qx if qx else all_cols
    nr,nc = len(row_ys),len(col_xs); grid = [[None]*nc for _ in range(nr)]
    for b in blocks:
        cx,cy = (b["x1"]+b["x2"])/2,(b["y1"]+b["y2"])/2
        r = min(range(nr),key=lambda i:abs(row_ys[i]-cy))
        c = min(range(nc),key=lambda j:abs(col_xs[j]-cx))
        if grid[r][c] is None or b["confidence"]>grid[r][c].get("confidence",0): grid[r][c]=b
    return grid,row_ys,col_xs


def split_into_tables(grid):
    sec = re.compile(r'^[二三四五六七八九十]、'); breaks = [0]
    for r in range(1,len(grid)):
        if sec.match(" ".join([c["text"] for c in grid[r] if c])): breaks.append(r)
    breaks.append(len(grid))
    return [grid[breaks[i]:breaks[i+1]] for i in range(len(breaks)-1) if len(grid[breaks[i]:breaks[i+1]])>=3]

