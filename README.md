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
- AWS S3 integration for file storage and cleanup
- Scheduled cleanup of temporary files

---

## Tech Stack

- **Backend**: Python 3.11, FastAPI, Starlette
- **Document Processing**: `pdfplumber`, `python-docx`, `docxtpl`, `pytesseract`, `Pillow`
- **LLM & Embeddings**: OpenRouter API (Llama 4 Maverick), `tenacity`, `httpx`
- **Storage**: AWS S3 for file storage and management
- **Frontend**: Vanilla HTML, CSS, JavaScript
- **Deployment**:
  - Frontend: Vercel (Static)
  - Backend: Render (Python)
- **Linting & Formatting**: Black, isort, flake8, mypy, ruff

---

## Prerequisites

- Python 3.11+
- `pip`
- Tesseract OCR (for image text extraction):
  ```bash
  # macOS
  brew install tesseract
  ```
- AWS Account with S3 bucket
- OpenRouter API key

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
   # API Keys
   API_KEY=<your-api-key>
   OPENROUTER_API_KEY=<your-openrouter-key>
   MODEL_ID=meta-llama/llama-4-maverick:free

   # AWS Configuration
   AWS_ACCESS_KEY_ID=<your-aws-key>
   AWS_SECRET_ACCESS_KEY=<your-aws-secret>
   AWS_REGION=eu-north-1
   S3_BUCKET_NAME=<your-bucket-name>

   # Application Settings
   REFERENCE_DIR=app/templates/reference
   TEMPLATE_PATH=app/templates/template.docx
   MAX_PROMPT_CHARS=4000000
   MAX_TOTAL_PROMPT_CHARS=4000000
   CLEANUP_TTL=900
   S3_CLEANUP_MAX_AGE_HOURS=24
   ```

---

## Running the Application

### Local Development

From the project root:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API endpoints are available under `http://localhost:8000/api/`
- The static frontend is served at `http://localhost:8000/`

### Deployment

#### Frontend (Vercel)
1. Push your code to GitHub
2. Connect your repository to Vercel
3. Configure environment variables in Vercel dashboard
4. Deploy

#### Backend (Render)
1. Create a new Web Service on Render
2. Connect your GitHub repository
3. Configure the following:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Environment Variables: Add all required variables from `.env`

---

## API Usage

**Endpoint**: `POST /api/generate`

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
curl -X POST https://your-backend-url/api/generate \
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

---

## Project Structure

```
report-ai/
├── app/                    # FastAPI backend
│   ├── api/               # REST endpoints
│   ├── core/              # Configuration, logging, cleanup
│   ├── services/          # Extraction, LLM pipeline, doc builder
│   └── templates/         # DOCX template & reference files
├── frontend/              # Static HTML/CSS/JS frontend
├── tests/                 # Test suite
├── requirements.txt       # Runtime dependencies
├── requirements-dev.txt   # Development dependencies
└── README.md             # Project documentation
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
- LLM powered by OpenRouter
- File storage by AWS S3
- Frontend deployed on Vercel
- Backend deployed on Render
