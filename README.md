# Report-AI

**AI-powered report generator for technical appraisals**

Report-AI enables you to upload documents (PDF, DOCX, Excel, images) and generate a complete appraisal report in Word (.docx) format using a multi-step LLM pipeline and customizable template.

---

## Features

- Extract text from PDF, DOCX, Excel (.xlsx, .xls), and images (OCR)
- Multi-step LLM pipeline: outline → expand sections → harmonize
- Inject generated content into a DOCX template
- FastAPI backend with robust error handling and logging
- Static HTML/CSS/JS frontend for easy interaction
- Scheduled cleanup of temporary files via Vercel serverless function

---

## Tech Stack

- **Backend**: Python 3.11, FastAPI, Starlette
- **Document Processing**: `pdfplumber`, `python-docx`, `docxtpl`, `pytesseract`, `Pillow`
- **LLM & Embeddings**: OpenAI / Hugging Face, `tenacity`, `httpx`, `sentence-transformers`
- **Frontend**: Vanilla HTML, CSS, JavaScript
- **Deployment**: Vercel (Python & Static)
- **Linting & Formatting**: Black, isort, flake8, mypy

---

## Prerequisites

- Python 3.11+
- `pip`
- Tesseract OCR (for image text extraction):
  ```bash
  # macOS
  brew install tesseract
  ```
- (Optional) Vercel CLI for local emulation:
  ```bash
  npm install -g vercel
  ```

---

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/report-ai.git
   cd report-ai
   ```

2. **Create a virtual environment**
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   Create a `.env` file in the project root and set the following:
   ```dotenv
   API_KEY=<your-api-key>
   OPENROUTER_API_KEY=<optional-openrouter-key>
   HF_API_TOKEN=<optional-huggingface-token>
   MODEL_ID=<llm-model-identifier>
   REFERENCE_DIR=app/templates/reference
   TEMPLATE_PATH=app/templates/template.docx
   ALLOW_VISION=true
   MAX_PROMPT_CHARS=4000000
   MAX_TOTAL_PROMPT_CHARS=4000000
   CLEANUP_TTL=900
   ```

---

## Running the Application

### Local Development

From the project root:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API endpoints are available under `http://localhost:8000/api/`.
- The static frontend is served at `http://localhost:8000/`.

### Vercel Deployment

The `vercel.json` configuration deploys the Python function and static assets:
```json
{
  "builds": [
    { "src": "app/main.py", "use": "@vercel/python" },
    { "src": "frontend/**", "use": "@vercel/static" }
  ],
  "routes": [
    { "src": "/api/(.*)", "dest": "app/main.py" },
    { "handle": "filesystem" },
    { "src": "/(.*)", "dest": "/frontend/$1" }
  ],
  "functions": {
    "api/cleanup.py": { "schedule": "@daily" }
  }
}
```

Deploy with:
```bash
vercel --prod
```

---

## API Usage

**Endpoint**: `POST /api/generate` (or `/generate` in local mode)

**Headers**:
- `X-API-Key`: Your `API_KEY` value

**Form Data**:
- `files`: One or more document files (`.pdf`, `.docx`, `.doc`, `.xlsx`, `.xls`, images)
- `notes`: (Optional) Additional notes for the report

**Response**:
- `200 OK`: Returns a `.docx` file (`report.docx`)
- `413 Payload Too Large`: Exceeded file or prompt size limits
- Other errors: JSON or plain text message

**Example**:
```bash
curl -X POST http://localhost:8000/api/generate \
  -H "X-API-Key: $API_KEY" \
  -F "files=@injury_report.pdf" \
  -F "notes=Include weather conditions" \
  --output report.docx
```

---

## Testing

### Unit Tests

Run all unit tests with:
```bash
pytest --maxfail=1 --disable-warnings -v
```

### Test Fixtures

To test with real documents and images, add your sample files under `tests/fixtures/`. For example:
```
tests/fixtures/sample.docx
tests/fixtures/sample.pdf
tests/fixtures/sample.png
```
These fixture files are ignored by Git (see `.gitignore`).

### End-to-End Tests

Place E2E tests under `tests/e2e/`, such as `tests/e2e/test_generate.py`. Example:

```python
import io
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def mock_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "testkey")
    monkeypatch.setattr("app.core.security.verify_api_key", lambda *args, **kwargs: True)


def test_generate_endpoint(monkeypatch):
    monkeypatch.setenv("API_KEY", "testkey")
    monkeypatch.setattr("app.services.llm.call_llm", lambda *_: '{"client":"","client_address1":"","client_address2":"","date":"","vs_rif":"","rif_broker":"","polizza":"","ns_rif":"","assicurato":"","indirizzo_ass1":"","indirizzo_ass2":"","luogo":"","data_danno":"","cause":"","data_incarico":"","merce":"","peso_merce":"","valore_merce":"","data_intervento":"","dinamica_eventi":"","accertamenti":"","quantificazione":"","commento":"","allegati":""}')
    monkeypatch.setattr("app.services.pipeline.PipelineService.run", lambda *a, **k: {"dinamica_eventi":"","accertamenti":"","quantificazione":"","commento":""})
    monkeypatch.setattr("app.services.doc_builder.inject", lambda *a, **k: b"DOCXBYTES")

    response = client.post(
        "/api/generate",
        headers={"X-API-Key": "testkey"},
        files={"files": ("sample.docx", b"PK\x03\x04", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    )
    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith(".docx")
```

---

## Project Structure

```
report-ai/
├── app/                    # FastAPI backend
│   ├── api/                # REST endpoints
│   ├── core/               # Configuration, logging, cleanup
│   ├── services/           # Extraction, LLM pipeline, doc builder
│   └── templates/          # DOCX template & reference files
├── api/                    # Scheduled serverless functions (cleanup)
├── frontend/               # Static HTML/CSS/JS frontend
├── scripts/                # Utility scripts
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Development dependencies
├── vercel.json             # Vercel deployment settings
├── mypy.ini, .flake8, etc. # Linting/formatting configs
└── README.md               # Project documentation
```

---

## Contributing

1. Fork the repository
2. Create a new branch (`git checkout -b feature/awesome`)
3. Make your changes and commit (`git commit -m "Add awesome feature"`)
4. Run linting & tests:
   ```bash
   pre-commit run --all-files
   mypy app
   flake8
   ```
5. Push to your branch and open a Pull Request

---

## License

This project does not include a license file. Consider adding an open-source license (e.g., MIT, Apache 2.0) in `LICENSE`.

---

## Acknowledgments

- Powered by FastAPI
- Document templating by `docxtpl` and `python-docx`
- Embeddings via `sentence-transformers`
- Deployed on Vercel
