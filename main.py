from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from routes.directory import router as directory_router
from pathlib import Path
# import dotenv
# import os

# ROOT_DIR = Path(__file__).resolve().parents[2]
# dotenv.load_dotenv(ROOT_DIR / ".env")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000"
    ],  # React app origin
    allow_credentials=True,                   # must be True for cookies
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(directory_router, prefix="/directory")
