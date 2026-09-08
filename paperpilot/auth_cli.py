"""Offline administration for the local PaperPilot identity store."""

from __future__ import annotations

import argparse
import getpass
import os

from flask import Flask

from paperpilot.database import connection
from paperpilot.database.db_manager import init_db_schema
from paperpilot.local_auth import LocalAuthError, LocalAuthService


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PaperPilot local account administration")
    parser.add_argument("--db", default=os.getenv("PAPERPILOT_DB_PATH", "db/paperpilot.db"))
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin")
    create.add_argument("--username", required=True)
    reset = commands.add_parser("reset-password")
    reset.add_argument("--username", required=True)
    args = parser.parse_args(argv)

    connection.DB_PATH = os.path.abspath(args.db)
    init_db_schema(connection.DB_PATH)
    flask_app = Flask("paperpilot-auth-cli")
    try:
        with flask_app.app_context():
            service = LocalAuthService()
            password = getpass.getpass("Temporary password: ")
            confirmation = getpass.getpass("Confirm temporary password: ")
            if password != confirmation:
                parser.error("passwords do not match")
            if args.command == "create-admin":
                service.create_bootstrap_admin(args.username, password)
                print("administrator created; password change is required at first login")
            else:
                normalized = args.username.strip().lower()
                row = connection.get_db().execute(
                    "SELECT id FROM users WHERE username_normalized=?", (normalized,)
                ).fetchone()
                if row is None:
                    raise LocalAuthError("user_not_found")
                database = connection.get_db()
                now = int(service._now())
                database.execute(
                    """UPDATE users SET password_hash=?,must_change_password=1,
                       updated_at=? WHERE id=?""",
                    (service._passwords.hash(password), now, row["id"]),
                )
                database.execute(
                    "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                    (now, row["id"]),
                )
                database.commit()
                print("password reset; password change is required at next login")
    except LocalAuthError as exc:
        parser.error(exc.reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
