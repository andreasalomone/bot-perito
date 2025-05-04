from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.core.cleanup import start_tmp_sweeper
from app.api.routes import router

app = FastAPI(title="Report-AI MVP")
app.include_router(router)
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")

start_tmp_sweeper()