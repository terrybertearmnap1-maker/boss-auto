"""把被流水线覆盖成 agent-pipeline 的真实岗位改回 zhipin。"""

import sqlite3

DB = r"C:\Users\EDY\Documents\deepseek-harness\default-workspace\boss-auto\jobpilot\jobpilot.db"

conn = sqlite3.connect(DB)
cur = conn.execute(
    "UPDATE jobs SET source = 'zhipin' "
    "WHERE url LIKE '%job_detail%' AND length(jd) > 150 AND source != 'zhipin'"
)
conn.commit()
print("恢复为真实岗位:", cur.rowcount, "条")

for row in conn.execute("SELECT source, COUNT(*) FROM jobs GROUP BY source"):
    print(" ", row[0], row[1])
