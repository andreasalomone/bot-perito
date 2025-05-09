from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.core.logging import setup_logging
from app.services.doc_builder import DocBuilderError
from app.services.extractor import ExtractorError
from app.services.llm import JSONParsingError, LLMError
from app.services.pipeline import PipelineError
from app.services.rag import RAGError

setup_logging()

app = FastAPI(title="Report-AI MVP")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        {"error": "Input validation failed", "details": exc.errors()},
        status_code=422,
    )


@app.exception_handler(ExtractorError)
async def extractor_exception_handler(request, exc):
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.exception_handler(RAGError)
async def rag_exception_handler(request, exc):
    return JSONResponse({"error": str(exc)}, status_code=500)


@app.exception_handler(PipelineError)
async def pipeline_exception_handler(request, exc):
    return JSONResponse({"error": str(exc)}, status_code=500)


@app.exception_handler(DocBuilderError)
async def docbuilder_exception_handler(request, exc):
    return JSONResponse({"error": str(exc)}, status_code=500)


@app.exception_handler(LLMError)
async def llm_exception_handler(request, exc):
    return JSONResponse({"error": str(exc)}, status_code=500)


@app.exception_handler(JSONParsingError)
async def jsonparsing_exception_handler(request, exc):
    return JSONResponse({"error": str(exc)}, status_code=500)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[  # allow local dev
        "https://aiperito.vercel.app",
        "http://localhost:3000",
        "http://localhost:8000",
        "https://localhost:3000",
        "https://localhost:8000",
    ],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(router)
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
