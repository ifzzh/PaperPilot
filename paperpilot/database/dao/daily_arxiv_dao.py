import json
from ..connection import get_db
from paperpilot.security.identity import current_user_id

class DailyArxivDAO:
    @staticmethod
    def save_task(date, category, status, metadata=None):
        db = get_db()
        metadata_json = json.dumps(metadata) if metadata else None
        db.execute('INSERT OR REPLACE INTO daily_arxiv_tasks_v2 (owner_id,date,category,status,metadata) VALUES (?,?,?,?,?)',
                   (current_user_id(), date, category, status, metadata_json))
        db.commit()

    @staticmethod
    def get_task(date, category):
        db = get_db()
        row = db.execute('SELECT * FROM daily_arxiv_tasks_v2 WHERE owner_id=? AND date=? AND category=?', (current_user_id(), date, category)).fetchone()
        if row:
            d = dict(row)
            if d['metadata']:
                try:
                    d['metadata'] = json.loads(d['metadata'])
                except:
                    pass
            return d
        return None
