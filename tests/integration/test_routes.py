import io
from typing import List

import pytest
from fastapi import FastAPI, status
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

# Router under test
from app.api import routes as routes_module

# Domain exceptions
from app.core.exceptions import PipelineError
from app.services.doc_builder import DocBuilderError
from app.models.report_models import ReportContext

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fastapi_app(monkeypatch):
    """Return a FastAPI app with router under test and overrides applied."""

    app = FastAPI()
    app.include_router(routes_module.router)

    # Disable API-key verification during tests
    app.dependency_overrides[routes_module.verify_api_key] = lambda: True

    return app


# ---------------------------------------------------------------------------
# Helper dummy implementations
# ---------------------------------------------------------------------------

async def _dummy_stream(*_args, **_kwargs):
    """Async generator that yields a single NDJSON line."""
    yield "{\"type\":\"status\",\"message\":\"ok\"}\n"


def _sync_docx_response() -> StreamingResponse:
    """Return a trivial StreamingResponse representing a DOCX file."""
    return StreamingResponse(iter([b"DOCX_BYTES"]), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


async def _async_docx_response(*_args, **_kwargs):
    return _sync_docx_response()


async def _async_report_context(*_args, **_kwargs):
    return ReportContext()


# ---------------------------------------------------------------------------
# /api/generate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("notes", ["", "some user notes"])
def test_generate_success(fastapi_app, monkeypatch, notes):
    # Patch the heavy streaming function
    monkeypatch.setattr(
        routes_module,
        "_stream_report_generation_logic",
        lambda files, notes: _dummy_stream(),
    )

    client = TestClient(fastapi_app)

    files = {"files": ("dummy.pdf", b"%PDF-1.4\n", "application/pdf")}
    resp = client.post("/api/generate", files=files, data={"notes": notes})

    assert resp.status_code == status.HTTP_200_OK
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    assert "ok" in resp.text


# ---------------------------------------------------------------------------
# /api/generate-with-clarifications
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_with_clarifications_success(fastapi_app, monkeypatch):
    # Mock build_report_with_clarifications to return an empty ReportContext
    monkeypatch.setattr(
        routes_module,
        "build_report_with_clarifications",
        _async_report_context,
    )

    monkeypatch.setattr(routes_module, "_generate_and_stream_docx", _async_docx_response)

    client = TestClient(fastapi_app)

    payload = {
        "clarifications": {},
        "request_artifacts": {
            "original_corpus": "",
            "image_tokens": [],
            "notes": "",
            "template_excerpt": "",
            "reference_style_text": "",
            "initial_llm_base_fields": {},
        },
    }
    resp = client.post("/api/generate-with-clarifications?request_id=cli", json=payload)

    assert resp.status_code == status.HTTP_200_OK
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument")


@pytest.mark.parametrize(
    "raised_exc, expected_status",
    [
        (PipelineError("Prompt too large"), 413),
        (PipelineError("Malformed data"), 400),
        (DocBuilderError("doc build fail"), 500),
    ],
)
def test_generate_with_clarifications_error_paths(fastapi_app, monkeypatch, raised_exc, expected_status):
    async def _raise_async(*_a, **_kw):
        raise raised_exc

    # Monkeypatch according to which function should raise
    if isinstance(raised_exc, DocBuilderError):
        monkeypatch.setattr(
            routes_module,
            "build_report_with_clarifications",
            _async_report_context,
        )
        monkeypatch.setattr(routes_module, "_generate_and_stream_docx", _raise_async)
    else:
        monkeypatch.setattr(routes_module, "build_report_with_clarifications", lambda *a, **kw: (_ for _ in ()).throw(raised_exc))
        # Provide async docx response for downstream call
        monkeypatch.setattr(routes_module, "_generate_and_stream_docx", _async_docx_response)

    client = TestClient(fastapi_app)
    payload = {
        "clarifications": {},
        "request_artifacts": {
            "original_corpus": "",
            "image_tokens": [],
            "notes": "",
            "template_excerpt": "",
            "reference_style_text": "",
            "initial_llm_base_fields": {},
        },
    }
    resp = client.post("/api/generate-with-clarifications?request_id=cli", json=payload)

    assert resp.status_code == expected_status


# ---------------------------------------------------------------------------
# /api/finalize-report
# ---------------------------------------------------------------------------

def test_finalize_report_success(fastapi_app, monkeypatch):
    monkeypatch.setattr(routes_module, "_generate_and_stream_docx", _async_docx_response)

    client = TestClient(fastapi_app)

    payload = {}
    resp = client.post("/api/finalize-report?request_id=cli", json=payload)

    assert resp.status_code == status.HTTP_200_OK
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument")


@pytest.mark.parametrize(
    "raised_exc, expected_status",
    [
        (PipelineError("Prompt too large"), 413),
        (PipelineError("Malformed data"), 400),
        (DocBuilderError("doc build fail"), 500),
    ],
)
def test_finalize_report_error_paths(fastapi_app, monkeypatch, raised_exc, expected_status):
    # For finalize-report, _generate_and_stream_docx is the only place errors originate
    async def _raise_async(*_a, **_kw):
        raise raised_exc

    monkeypatch.setattr(routes_module, "_generate_and_stream_docx", _raise_async)

    client = TestClient(fastapi_app)
    payload = {}
    resp = client.post("/api/finalize-report?request_id=cli", json=payload)

    assert resp.status_code == expected_status
