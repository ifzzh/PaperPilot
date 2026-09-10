"""Browser cold-start fixture: existing synthetic assets, empty process cache."""
import signal
import tempfile
from pytest import MonkeyPatch
from werkzeug.serving import make_server
import app as app_module
from tests.workbench_support import make_workbench_fixture

if __name__ == '__main__':
    def stop(*_args):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    with tempfile.TemporaryDirectory(prefix='paperpilot-cold-') as directory, MonkeyPatch.context() as patch:
        application, first, second = make_workbench_fixture(directory, patch, count=6, cold=True)
        with application.app_context():
            _, invitation = app_module.AUTH_SERVICE.create_invite(first['id'])
            app_module.AUTH_SERVICE.register('empty_reader', 'workbench-test-pass', invitation)
        server = make_server('127.0.0.3', 7191, application, threaded=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
