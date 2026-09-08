from ..connection import get_db
from paperpilot.security.identity import current_user_id

class CategoryDAO:
    @staticmethod
    def get_all_categories():
        db = get_db()
        rows = db.execute('SELECT * FROM categories WHERE owner_id=?', (current_user_id(),)).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def save_category(id, name, parent_id=None, display_name=None):
        db = get_db()
        cursor = db.execute(
            '''INSERT INTO categories (id,owner_id,name,parent_id,display_name)
               VALUES (?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                   parent_id=excluded.parent_id,display_name=excluded.display_name
               WHERE categories.owner_id=excluded.owner_id''',
            (id, current_user_id(), name, parent_id, display_name),
        )
        if cursor.rowcount != 1:
            db.rollback()
            raise PermissionError("category_not_found")
        db.commit()
            
    @staticmethod
    def clear_categories():
        db = get_db()
        db.execute('DELETE FROM categories WHERE owner_id=?', (current_user_id(),))
        db.commit()
