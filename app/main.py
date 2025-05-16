import logging

from fastapi import FastAPI
from fastapi import Request
from fastapi import status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.core.config import settings
from app.core.logging import setup_logging
from app.services.doc_builder import DocBuilderError
from app.services.llm import JSONParsingError
from app.services.llm import LLMError
from app.services.pipeline import PipelineError

setup_logging()

app = FastAPI(title="Report-AI MVP")

logger = logging.getLogger(__name__)


# Add startup event with log test
@app.on_event("startup")
async def startup_event() -> None:
    logger.debug("DEBUG: Application startup - debug message")
    logger.info("INFO: Application startup - Application started successfully")


# Add test endpoint for logging
@app.get("/testlog", tags=["Debug"])
async def test_logging() -> dict[str, str]:
    logger.debug("DEBUG: Test endpoint - debug message")
    logger.info("INFO: Test endpoint - info message")
    return {"status": "Logs generated, check server console"}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    logger.error(f"HTTP exception: {exc.detail} (status: {exc.status_code})")
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    # Log the detailed Pydantic validation errors to the server console
    logger.error("Request validation failed: %s", exc.errors(), exc_info=False)
    return JSONResponse(
        {"error": "Input validation failed", "details": exc.errors()},
        status_code=422,
    )


@app.exception_handler(PipelineError)
async def pipeline_exception_handler(_request: Request, exc: PipelineError) -> JSONResponse:
    logger.error(f"Pipeline error: {str(exc)}")
    return JSONResponse({"error": str(exc)}, status_code=500)


@app.exception_handler(DocBuilderError)
async def docbuilder_exception_handler(_request: Request, exc: DocBuilderError) -> JSONResponse:
    logger.error(f"DocBuilder error: {str(exc)}")
    return JSONResponse({"error": str(exc)}, status_code=500)


@app.exception_handler(LLMError)
async def llm_exception_handler(_request: Request, exc: LLMError) -> JSONResponse:
    logger.error(f"LLM error: {str(exc)}")
    return JSONResponse({"error": str(exc)}, status_code=500)


@app.exception_handler(JSONParsingError)
async def jsonparsing_exception_handler(_request: Request, exc: JSONParsingError) -> JSONResponse:
    logger.error(f"JSON parsing error: {str(exc)}")
    return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/health", status_code=status.HTTP_200_OK, tags=["Health"])
async def health_check() -> dict[str, str]:
    logger.info("Health check endpoint called")
    return {"status": "ok"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(router)
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
