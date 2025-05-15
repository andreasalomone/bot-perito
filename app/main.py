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


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        {"error": "Input validation failed", "details": exc.errors()},
        status_code=422,
    )


@app.exception_handler(PipelineError)
async def pipeline_exception_handler(_request: Request, exc: PipelineError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=500)


@app.exception_handler(DocBuilderError)
async def docbuilder_exception_handler(_request: Request, exc: DocBuilderError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=500)


@app.exception_handler(LLMError)
async def llm_exception_handler(_request: Request, exc: LLMError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=500)


@app.exception_handler(JSONParsingError)
async def jsonparsing_exception_handler(_request: Request, exc: JSONParsingError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/health", status_code=status.HTTP_200_OK, tags=["Health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(router)
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
