import json
from ..connection import get_db
from ipaper.security.identity import current_user_id

class ReadingHistoryDAO:
    @staticmethod
    def add_history(date, duration, paper_id, timestamp):
        db = get_db()
        db.execute('INSERT INTO reading_history (date,duration,paper_id,timestamp,owner_id) VALUES (?,?,?,?,?)',
                   (date, duration, paper_id, timestamp, current_user_id()))
        db.commit()

    @staticmethod
    def get_history(limit=None):
        db = get_db()
        sql = 'SELECT * FROM reading_history WHERE owner_id=? ORDER BY timestamp DESC'
        if limit:
            sql += f' LIMIT {limit}'
        rows = db.execute(sql, (current_user_id(),)).fetchall()
        return [dict(row) for row in rows]
        
    @staticmethod
    def get_history_by_date(date):
        db = get_db()
        rows = db.execute('SELECT * FROM reading_history WHERE date=? AND owner_id=?', (date, current_user_id())).fetchall()
        return [dict(row) for row in rows]

class ReadingListDAO:
    @staticmethod
    def add_item(paper_id, added_at, status='unread'):
        db = get_db()
        cursor = db.execute(
            '''INSERT INTO reading_list (paper_id,owner_id,added_at,status)
               VALUES (?,?,?,?)
               ON CONFLICT(paper_id) DO UPDATE SET
                   added_at=excluded.added_at,status=excluded.status
               WHERE reading_list.owner_id=excluded.owner_id''',
            (paper_id, current_user_id(), added_at, status),
        )
        if cursor.rowcount != 1:
            db.rollback()
            raise PermissionError("reading_list_item_not_found")
        db.commit()

    @staticmethod
    def get_list():
        db = get_db()
        rows = db.execute('SELECT * FROM reading_list WHERE owner_id=? ORDER BY added_at DESC', (current_user_id(),)).fetchall()
        return [dict(row) for row in rows]
        
    @staticmethod
    def remove_item(paper_id):
        db = get_db()
        db.execute('DELETE FROM reading_list WHERE paper_id=? AND owner_id=?', (paper_id, current_user_id()))
        db.commit()


class DailyArxivReadDAO:
    @staticmethod
    def mark_read(arxiv_id: str, read_at: int) -> None:
        if not arxiv_id:
            return
        db = get_db()
        db.execute(
            "INSERT OR REPLACE INTO daily_arxiv_reads_v2 (owner_id,arxiv_id,read_at) VALUES (?,?,?)",
            (current_user_id(), arxiv_id, int(read_at)),
        )
        db.commit()

    @staticmethod
    def get_read_ids(arxiv_ids):
        if not arxiv_ids:
            return []

        cleaned = [x for x in arxiv_ids if isinstance(x, str) and x.strip()]
        if not cleaned:
            return []

        placeholders = ",".join(["?"] * len(cleaned))
        db = get_db()
        rows = db.execute(
            f"SELECT arxiv_id FROM daily_arxiv_reads_v2 WHERE owner_id=? AND arxiv_id IN ({placeholders})",
            (current_user_id(), *cleaned),
        ).fetchall()
        return [dict(r).get("arxiv_id") for r in rows if dict(r).get("arxiv_id")]
