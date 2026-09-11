"""No network: release probe must accept the route's whitespace normalization."""
import io,json,sys
import pytest
from types import SimpleNamespace as N
from tests import p0_live_chat as probe


@pytest.mark.parametrize("with_selection", [False, True])
def test_probe_accepts_persisted_trimmed_stream(tmp_path,monkeypatch,with_selection):
    class Fake:
        def __init__(self,**kwargs):
            assert kwargs['max_retries']==0 and kwargs['timeout']==120
            def create(**kw):
                assert kw['max_completion_tokens']==512
                if with_selection: assert '引用《合成论文》原文第 1 页' in kw['messages'][-1]['content']
                return iter([N(choices=[N(delta=N(content=' 已收到合成样例。\n'),finish_reason='stop')])])
            self.chat=N(completions=N(create=create))
        def close(self):pass
    monkeypatch.setattr(probe,'OpenAI',Fake)
    monkeypatch.setattr(probe.OutboundPolicy,'validate',lambda *_a,**_k:None)
    argv=['probe','--live','--evidence',str(tmp_path/'evidence')]
    if with_selection:
        sample=tmp_path/'sample.json';sample.write_text(json.dumps(dict(title='合成论文',document='original',page=1,quote='Synthetic excerpt',question='解释此段')))
        argv += ['--selection-sample',str(sample)]
    monkeypatch.setattr(sys,'argv',argv)
    monkeypatch.setattr(sys,'stdin',io.TextIOWrapper(io.BytesIO(json.dumps({'token':'fake','origin':'https://fake.invalid','base_url':'https://fake.invalid/v1','model':'fake'}).encode())))
    probe.main()
    assert json.loads((tmp_path/'evidence/result.json').read_text())['passed']
