import os

from deepgram import DeepgramClient
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.transcription import router as transcription_router
from app.post_meeting import router as post_meeting_router
from app.adviser_learning import router as adviser_learning_router
from app.voice import router as voice_router

load_dotenv()

app = FastAPI(title="AI Compassion Coach API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Voice-Mode"],
)

app.include_router(transcription_router)
app.include_router(post_meeting_router)
app.include_router(voice_router)
app.include_router(adviser_learning_router)

deepgram = DeepgramClient(
    api_key=os.environ["DEEPGRAM_API_KEY"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/deepgram/health")
def deepgram_health():
    deepgram.manage.v1.projects.list()
    return {"status": "ok"}
