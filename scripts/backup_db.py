# -*- coding: utf-8 -*-
"""每日镜像备份：本地主库 db/ → 网盘备份目录（覆盖式镜像 /MIR）。

robocopy 退出码 0-7 视为成功（8+ 为错误）。日志追加到 output/backup_db.log。
"""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config

SRC = str(config.DB_DIR)
DST = str(config.BACKUP_DIR)
LOG = config.OUTPUT_DIR / "backup_db.log"
LOG.parent.mkdir(parents=True, exist_ok=True)

cmd = ["robocopy", SRC, DST, "/MIR", "/R:3", "/W:10", "/NP", "/NFL", "/NDL", "/LOG+:" + str(LOG)]
proc = subprocess.run(cmd)

rc = proc.returncode
ok = rc < 8
with open(LOG, "a", encoding="utf-8") as f:
    f.write(f"[backup_db.py] exit={rc} {'OK' if ok else 'FAIL'}\n")

print(f"[backup_db.py] exit={rc} {'OK' if ok else 'FAIL'}  {SRC} -> {DST}")
sys.exit(0 if ok else 1)
