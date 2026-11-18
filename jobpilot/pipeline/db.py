"""存储层：MySQL 优先，SQLite 兜底，统一接口。

为什么用 MySQL：岗位表要做去重（job_id 主键）、按决策/分数过滤、按时间排序，
还需要和看板并发读；SQLite 只适合本地演示，所以两者接口保持一致，
通过 DATABASE_URL 切换，代码里不出现方言分支以外的差异。
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional

DDL = """
CREATE TABLE IF NOT EXISTS jobs (
  job_id      VARCHAR(64)  PRIMARY KEY,
  title       VARCHAR(255),
  company     VARCHAR(255),
  salary      VARCHAR(64),
  url         VARCHAR(512),
  source      VARCHAR(32),
  score       INT,
  decision    VARCHAR(16),
  reason      VARCHAR(255),
  matched     VARCHAR(255),
  greeting    TEXT,
  penalty     INT,
  penalty_reasons VARCHAR(255),
  jd          TEXT,
  created_at  VARCHAR(32)
)
"""

COLUMNS = ["job_id", "title", "company", "salary", "url", "source",
           "score", "decision", "reason", "matched", "greeting",
           "penalty", "penalty_reasons", "jd", "created_at"]

# 老库缺列时自动补，避免为了加字段让人删库重来
MIGRATIONS = [
    ("penalty", "INT"),
    ("penalty_reasons", "VARCHAR(255)"),
]


class BaseDB:
    backend = "base"

    def init(self) -> None:
        raise NotImplementedError

    def upsert(self, row: Dict[str, Any]) -> None:
        raise NotImplementedError

    def list_jobs(self, limit: int = 50, decision: Optional[str] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def stats(self) -> Dict[str, Any]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SQLiteDB(BaseDB):
    backend = "sqlite"

    def __init__(self, path: str) -> None:
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def init(self) -> None:
        self.conn.execute(DDL)
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(jobs)")}
        for name, sql_type in MIGRATIONS:
            if name not in cols:
                self.conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {sql_type}")
        self.conn.commit()

    def upsert(self, row: Dict[str, Any]) -> None:
        row = {**row, "created_at": row.get("created_at") or time.strftime("%Y-%m-%d %H:%M:%S")}
        # 岗位来源是「真实/模拟」的标记，流水线回写结果时不能把它覆盖掉，
        # 否则真实岗位写一次就变成 agent-pipeline，之后再也选不中
        if row.get("source") != "zhipin":
            hit = self.conn.execute("SELECT source FROM jobs WHERE job_id = ?",
                                    (row.get("job_id"),)).fetchone()
            if hit and hit["source"] == "zhipin":
                row["source"] = "zhipin"
        placeholders = ",".join("?" for _ in COLUMNS)
        sql = (f"INSERT INTO jobs ({','.join(COLUMNS)}) VALUES ({placeholders}) "
               f"ON CONFLICT(job_id) DO UPDATE SET "
               + ",".join(f"{c}=excluded.{c}" for c in COLUMNS if c != "job_id"))
        self.conn.execute(sql, [row.get(c) for c in COLUMNS])
        self.conn.commit()

    def list_jobs(self, limit: int = 50, decision: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM jobs"
        args: List[Any] = []
        if decision:
            sql += " WHERE decision = ?"
            args.append(decision)
        sql += " ORDER BY created_at DESC, score DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def stats(self) -> Dict[str, Any]:
        cur = self.conn.execute(
            "SELECT decision, COUNT(*) c, AVG(score) avg_score FROM jobs GROUP BY decision"
        )
        by_decision = {r["decision"]: r["c"] for r in cur.fetchall()}
        total = self.conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
        avg = self.conn.execute("SELECT AVG(score) s FROM jobs").fetchone()["s"]
        return {
            "total": total,
            "apply": by_decision.get("apply", 0),
            "skip": by_decision.get("skip", 0),
            "avg_score": round(avg or 0, 1),
        }


class MySQLDB(BaseDB):
    backend = "mysql"

    def __init__(self, dsn: str) -> None:
        import pymysql
        from urllib.parse import urlparse

        u = urlparse(dsn)
        self.conn = pymysql.connect(
            host=u.hostname or "127.0.0.1",
            port=u.port or 3306,
            user=u.username or "root",
            password=u.password or "",
            database=(u.path or "/jobpilot").lstrip("/"),
            charset="utf8mb4",
            autocommit=True,
        )
        self._pymysql = pymysql

    def init(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute(DDL)
            for name, sql_type in MIGRATIONS:
                try:
                    cur.execute(f"ALTER TABLE jobs ADD COLUMN {name} {sql_type}")
                except Exception:  # noqa: BLE001
                    pass  # 列已存在

    def upsert(self, row: Dict[str, Any]) -> None:
        row = {**row, "created_at": row.get("created_at") or time.strftime("%Y-%m-%d %H:%M:%S")}
        placeholders = ",".join(["%s"] * len(COLUMNS))
        sql = (f"INSERT INTO jobs ({','.join(COLUMNS)}) VALUES ({placeholders}) "
               f"ON DUPLICATE KEY UPDATE "
               + ",".join(f"{c}=VALUES({c})" for c in COLUMNS if c != "job_id"))
        with self.conn.cursor() as cur:
            cur.execute(sql, [row.get(c) for c in COLUMNS])

    def list_jobs(self, limit: int = 50, decision: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM jobs"
        args: List[Any] = []
        if decision:
            sql += " WHERE decision = %s"
            args.append(decision)
        sql += " ORDER BY created_at DESC, score DESC LIMIT %s"
        args.append(limit)
        with self.conn.cursor() as cur:
            cur.execute(sql, args)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def stats(self) -> Dict[str, Any]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT decision, COUNT(*) FROM jobs GROUP BY decision")
            by_decision = {r[0]: r[1] for r in cur.fetchall()}
            cur.execute("SELECT COUNT(*), AVG(score) FROM jobs")
            total, avg = cur.fetchone()
        return {
            "total": total or 0,
            "apply": by_decision.get("apply", 0),
            "skip": by_decision.get("skip", 0),
            "avg_score": round(float(avg or 0), 1),
        }

    def close(self) -> None:
        self.conn.close()


def build_db(dsn: str) -> BaseDB:
    """按 DSN 选择实现；连不上 MySQL 时降级 SQLite，保证服务起得来。"""
    if dsn.startswith("mysql"):
        try:
            db = MySQLDB(dsn)
            db.init()
            return db
        except Exception as exc:  # noqa: BLE001
            print(f"[db] MySQL 不可用（{exc}），降级 SQLite")
    path = dsn.replace("sqlite:///", "") if dsn.startswith("sqlite:///") else "./jobpilot.db"
    db = SQLiteDB(path)
    db.init()
    return db
