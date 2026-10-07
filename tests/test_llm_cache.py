import concurrent.futures as cf
from halo.run.llm import LLM


def test_concurrent_misses_share_one_reply(tmp_path, monkeypatch):
    calls = []

    def fake(self, prompt):
        import time
        calls.append(prompt); time.sleep(0.2)
        return f'reply {len(calls)}'

    monkeypatch.setattr(LLM, '_call', fake)
    llm = LLM('mock:x', cache_dir=tmp_path)
    with cf.ThreadPoolExecutor(4) as ex:
        out = list(ex.map(lambda _: llm('sys', 'same user message', tag='t'), range(4)))
    assert len(calls) == 1 and len(set(out)) == 1
