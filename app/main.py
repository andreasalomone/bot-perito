from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.core.logging import setup_logging
from app.core.models import embedding_model

setup_logging()

app = FastAPI(title="Report-AI MVP")


@app.on_event("startup")
def load_models():
    # Preload embedding model to avoid cold-start latency
    _ = embedding_model


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        {"error": "Input validation failed", "details": exc.errors()},
        status_code=422,
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://aiperito.vercel.app",
        "https://localhost:3000",
        "https://localhost:8000",
    ],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(router)
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
