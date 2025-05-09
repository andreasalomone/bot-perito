from types import SimpleNamespace

import pytest
import requests

from app.core.embeddings import _get_headers, embed


def test_get_headers_no_token(monkeypatch):
    # Remove any existing HF tokens
    monkeypatch.delenv("HF_API_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACEHUB_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError) as exc:
        _get_headers()
    assert "HF API token not found" in str(exc.value)


def test_get_headers_from_hf_api(monkeypatch):
    # Provide HF_API_TOKEN
    monkeypatch.setenv("HF_API_TOKEN", "abc123")
    headers = _get_headers()
    assert headers == {"Authorization": "Bearer abc123"}


def test_embed_success(monkeypatch):
    # Ensure token present
    monkeypatch.setenv("HF_API_TOKEN", "token123")
    # Fake response object
    fake_res = SimpleNamespace()
    fake_res.raise_for_status = lambda: None
    fake_res.json = lambda: [[0.5, 0.6]]
    # Monkeypatch requests.post
    monkeypatch.setattr(
        "app.core.embeddings.requests.post", lambda url, headers, json: fake_res
    )
    result = embed("hello world")
    assert result == [0.5, 0.6]


def test_embed_request_error(monkeypatch):
    # Ensure token present
    monkeypatch.setenv("HF_API_TOKEN", "token123")

    # Fake response raising HTTPError
    class FakeRes:
        def raise_for_status(self):
            raise requests.HTTPError("failure")

        def json(self):
            return [[1.0]]

    monkeypatch.setattr(
        "app.core.embeddings.requests.post", lambda url, headers, json: FakeRes()
    )
    with pytest.raises(requests.HTTPError):
        embed("some text")
