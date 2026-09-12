from ..connection import get_db
from ipaper.security.identity import current_user_id

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

    @staticmethod
    def replace_tree(tree):
        import json
        if not isinstance(tree, dict) or tree.get('id') != 'root':
            raise ValueError('invalid_category_tree')
        rows, preferences, seen = [], {}, {'root'}
        def visit(node, parent_id, depth):
            if depth > 32 or len(rows) >= 2000 or not isinstance(node, dict):
                raise ValueError('invalid_category_tree')
            ident, name = node.get('id'), node.get('name')
            if not isinstance(ident, str) or not ident or ident in seen or not isinstance(name, str) or not name:
                raise ValueError('invalid_category_tree')
            seen.add(ident)
            rows.append((ident, name, parent_id, node.get('display_name')))
            preferences[ident] = {k: node[k] for k in ('color', 'pinned') if k in node}
            for child in node.get('children', []):
                visit(child, ident, depth + 1)
        for child in tree.get('children', []):
            visit(child, None, 1)
        db, owner = get_db(), current_user_id()
        try:
            db.execute('BEGIN IMMEDIATE')
            for ident, *_ in rows:
                existing = db.execute('SELECT owner_id FROM categories WHERE id=?', (ident,)).fetchone()
                if existing and existing['owner_id'] != owner:
                    raise PermissionError('category_not_found')
            db.execute("DELETE FROM categories WHERE owner_id=? AND id!='root'", (owner,))
            for ident, name, parent, display in rows:
                db.execute('INSERT INTO categories(id,owner_id,name,parent_id,display_name) VALUES(?,?,?,?,?)',
                           (ident, owner, name, parent, display))
            db.execute('INSERT INTO user_settings_v2(owner_id,key,value) VALUES(?,?,?) ON CONFLICT(owner_id,key) DO UPDATE SET value=excluded.value',
                       (owner, 'category_ui', json.dumps(preferences)))
            db.commit()
        except Exception:
            db.rollback()
            raise
