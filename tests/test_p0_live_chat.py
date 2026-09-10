"""No network: release probe must accept the route's whitespace normalization."""
import io,json,sys
from types import SimpleNamespace as N
from tests import p0_live_chat as probe


def test_probe_accepts_persisted_trimmed_stream(tmp_path,monkeypatch):
    class Fake:
        def __init__(self,**kwargs):
            assert kwargs['max_retries']==0 and kwargs['timeout']==120
            def create(**kw):
                assert kw['max_completion_tokens']==512
                return iter([N(choices=[N(delta=N(content=' 已收到合成样例。\n'),finish_reason='stop')])])
            self.chat=N(completions=N(create=create))
        def close(self):pass
    monkeypatch.setattr(probe,'OpenAI',Fake)
    monkeypatch.setattr(probe.OutboundPolicy,'validate',lambda *_a,**_k:None)
    monkeypatch.setattr(sys,'argv',['probe','--live','--evidence',str(tmp_path/'evidence')])
    monkeypatch.setattr(sys,'stdin',io.TextIOWrapper(io.BytesIO(json.dumps({'token':'fake','origin':'https://fake.invalid','base_url':'https://fake.invalid/v1','model':'fake'}).encode())))
    probe.main()
    assert json.loads((tmp_path/'evidence/result.json').read_text())['passed']
