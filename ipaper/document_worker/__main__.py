from werkzeug.serving import make_server

from .app import create_worker_app


def main() -> None:
    make_server("0.0.0.0", 7193, create_worker_app(), threaded=True).serve_forever()


if __name__ == "__main__":
    main()
