#!/usr/bin/env python3
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
p = (ROOT / 'runtime/audit.sqlite3').resolve()
if not p.is_file():
    raise SystemExit('No live audit DB yet.')
db=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True)
print(json.dumps({'event_counts':dict(db.execute('SELECT event,COUNT(*) FROM audit GROUP BY event').fetchall()),
                  'drafts':db.execute('SELECT COUNT(*) FROM drafts').fetchone()[0]},indent=2))
