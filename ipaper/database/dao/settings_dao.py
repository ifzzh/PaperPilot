import json
from ..connection import get_db
from ipaper.security.identity import current_user_id

class SettingsDAO:
    @staticmethod
    def get_setting(key, default=None):
        try:
            db = get_db()
            row = db.execute(
                'SELECT value FROM user_settings_v2 WHERE owner_id=? AND key=?',
                (current_user_id(), key),
            ).fetchone()
            if row:
                try:
                    return json.loads(row['value'])
                except:
                    return row['value']
            return default
        except Exception as e:
            print(f"Error getting setting {key}: {e}")
            return default

    @staticmethod
    def save_setting(key, value):
        try:
            db = get_db()
            db.execute(
                '''INSERT INTO user_settings_v2(owner_id,key,value) VALUES (?,?,?)
                   ON CONFLICT(owner_id,key) DO UPDATE SET value=excluded.value''',
                (current_user_id(), key, json.dumps(value)),
            )
            db.commit()
        except Exception as e:
            print(f"Error saving setting {key}: {e}")
