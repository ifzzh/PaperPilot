"""Offline administration for the local iPaper identity store."""

from __future__ import annotations

from ipaper.environment import getenv as brand_getenv

import argparse
import getpass
import os

from flask import Flask

from ipaper.database import connection
from ipaper.database.db_manager import init_db_schema
from ipaper.local_auth import LocalAuthError, LocalAuthService


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="iPaper local account administration")
    parser.add_argument("--db", default=brand_getenv("IPAPER_DB_PATH", "db/ipaper.db"))
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin")
    create.add_argument("--username", required=True)
    reset = commands.add_parser("reset-password")
    reset.add_argument("--username", required=True)
    args = parser.parse_args(argv)

    connection.DB_PATH = os.path.abspath(args.db)
    init_db_schema(connection.DB_PATH)
    flask_app = Flask("ipaper-auth-cli")
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
                service.offline_reset_password(args.username, password)
                print("password reset; password change is required at next login")
    except LocalAuthError as exc:
        parser.error(exc.reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
