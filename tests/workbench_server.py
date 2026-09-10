"""Browser acceptance server; synthetic data only, loopback port 7191."""
import signal
import tempfile
from pytest import MonkeyPatch
from werkzeug.serving import make_server
from tests.workbench_support import make_workbench_fixture
from tests.workbench_reader_support import fake_openai, install_reader_fixture

if __name__ == '__main__':
    def stop(_signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with tempfile.TemporaryDirectory(prefix='paperpilot-workbench-') as directory, MonkeyPatch.context() as patch, fake_openai() as origin:
        application, first, second = make_workbench_fixture(directory, patch, count=1000)
        with application.app_context():
            import app as app_module
            _, invitation = app_module.AUTH_SERVICE.create_invite(first['id'])
            third = app_module.AUTH_SERVICE.register('reader_pdf','workbench-test-pass',invitation)
        install_reader_fixture(application,directory,(first,second,third),patch,origin)
        # Distinct loopback address preserves the production 127.0.0.1:7191 listener.
        server = make_server('127.0.0.2', 7191, application, threaded=True)
        print('Synthetic workbench ready at http://127.0.0.2:7191', flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
