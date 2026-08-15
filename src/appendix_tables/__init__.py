"""总说明附录表格 — 每个表独立的解析和渲染逻辑。

每个模块导出 render(...) -> str
__init__.py 提供 render(page) 入口。
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TEXT_DIR = ROOT / "intermediate" / "text"

_PAGE_HANDLERS = {}
_MULTI_PAGE = {}  # page -> (module, [page_range])


def _register(page, module_name, multi_pages=None):
    _PAGE_HANDLERS[page] = module_name
    if multi_pages:
        _MULTI_PAGE[page] = multi_pages


# 各表模块
try:
    from . import table_1_p34
    _register(34, table_1_p34)
except ImportError:
    pass

try:
    from . import table_2_p35
    _register(35, table_2_p35)
except ImportError:
    pass

try:
    from . import app1_p36
    _register(36, app1_p36)
except ImportError:
    pass

try:
    from . import app2_p37_41
    for p in (37, 38, 39, 40, 41):
        _register(p, app2_p37_41, multi_pages=list(range(37, 42)))
except ImportError:
    pass

try:
    from . import app3_p42
    _register(42, app3_p42)
except ImportError:
    pass


def _load_page(pg):
    fpath = TEXT_DIR / f"page_{pg:04d}.json"
    if fpath.exists():
        with open(fpath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def render(page):
    """返回定制HTML或None（回退到通用逻辑）。"""
    handler = _PAGE_HANDLERS.get(page)
    if handler is None:
        return None

    multi = _MULTI_PAGE.get(page)
    if multi:
        pages = [_load_page(p) for p in multi]
        pages = [p for p in pages if p is not None]
        if not pages:
            return None
        return handler.render(*pages)

    page_data = _load_page(page)
    if page_data is None:
        return None
    return handler.render(page_data)
