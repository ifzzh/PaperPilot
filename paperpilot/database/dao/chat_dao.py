import json
from ..connection import get_db
from paperpilot.security.identity import current_user_id

class ChatDAO:
    @staticmethod
    def save_chat(session_id, data):
        db = get_db()
        paper_id = data.get('paper_id')
        history = json.dumps(data.get('history', []))
        created_at = data.get('created_at')
        updated_at = data.get('updated_at')
        title = data.get('title')
        
        cursor = db.execute('''INSERT INTO chats
                      (session_id,owner_id,paper_id,history,created_at,updated_at,title)
                      VALUES (?, ?, ?, ?, ?, ?, ?)
                      ON CONFLICT(session_id) DO UPDATE SET
                          paper_id=excluded.paper_id,history=excluded.history,
                          updated_at=excluded.updated_at,title=excluded.title
                      WHERE chats.owner_id=excluded.owner_id''',
                   (session_id, current_user_id(), paper_id, history, created_at, updated_at, title))
        if cursor.rowcount != 1:
            db.rollback()
            raise PermissionError("chat_not_found")
        db.commit()

    @staticmethod
    def get_chat(session_id):
        db = get_db()
        row = db.execute('SELECT * FROM chats WHERE session_id=? AND owner_id=?', (session_id, current_user_id())).fetchone()
        if row:
            d = dict(row)
            if d['history']:
                d['history'] = json.loads(d['history'])
            else:
                d['history'] = []
            return d
        return None

    @staticmethod
    def get_chats_by_paper(paper_id):
        db = get_db()
        rows = db.execute('SELECT * FROM chats WHERE paper_id=? AND owner_id=? ORDER BY updated_at DESC', (paper_id, current_user_id())).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            d['history'] = json.loads(d['history']) if d['history'] else []
            results.append(d)
        return results

    @staticmethod
    def delete_chat(session_id):
        db = get_db()
        db.execute('DELETE FROM chats WHERE session_id=? AND owner_id=?', (session_id, current_user_id()))
        db.commit()
