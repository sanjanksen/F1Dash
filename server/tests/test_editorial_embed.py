import editorial.embed as embed


class _FakeEmb:
    def __init__(self, v):
        self.values = v


class _FakeResp:
    def __init__(self, v):
        self.embeddings = [_FakeEmb(v)]


def _install_fake_genai(monkeypatch, models):
    # conftest stubs `requests`, so importing the real google.genai fails in
    # tests. Inject a fake google.genai into sys.modules so embed_texts'
    # `from google import genai` picks it up without the real import.
    import sys
    import types as pytypes

    class _Client:
        def __init__(self, **kw):
            self.models = models

    fake_genai = pytypes.ModuleType("google.genai")
    fake_genai.Client = _Client
    fake_types = pytypes.ModuleType("google.genai.types")
    fake_types.EmbedContentConfig = lambda **kw: dict(kw)
    fake_genai.types = fake_types

    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(embed.time, "sleep", lambda *_a, **_k: None)  # no real backoff waits


def test_embed_texts_retries_transient_429(monkeypatch):
    """A transient 429 on a chunk must be retried, not abort the whole batch."""
    calls = {"n": 0}

    class Models:
        def embed_content(self, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            return _FakeResp([0.1] * 1536)

    _install_fake_genai(monkeypatch, Models())
    out = embed.embed_texts(["hello"])

    assert out is not None
    assert out[0] is not None and len(out[0]) == 1536
    assert calls["n"] == 2  # retried once


def test_embed_texts_partial_when_one_chunk_keeps_failing(monkeypatch):
    """One permanently-failing chunk must not discard the whole article's
    embeddings — the rest still come back, that slot is None."""
    class Models:
        def embed_content(self, *, contents, **kw):
            if "BAD" in contents:
                raise RuntimeError("429 RESOURCE_EXHAUSTED")  # always fails
            return _FakeResp([0.2] * 1536)

    _install_fake_genai(monkeypatch, Models())
    out = embed.embed_texts(["good1", "BAD", "good2"])

    assert out is not None and len(out) == 3
    assert out[0] is not None and out[2] is not None
    assert out[1] is None  # failed chunk isolated, batch not aborted


def test_embed_texts_returns_none_without_key(monkeypatch):
    """No key → None (whole-batch unavailable) so callers fall back to FTS."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert embed.embed_texts(["hi"]) is None
