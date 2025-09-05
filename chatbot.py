# ai-backend/chatbot.py
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import main  # ini file Python kamu yang ada init_chatbot & get_response
import dtsen_scraper
import asyncio

app = FastAPI()

# CORS biar PHP / JS bisa akses
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ganti sesuai domain kalau mau aman
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Init chatbot sekali di awal
chatbot = main.init_chatbot()

class ChatRequest(BaseModel):
    message: str

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    question = req.message
    answer = chatbot.get_response(question)
    return {"answer": answer}

@app.get("/")
async def root():
    return {"message": "Chatbot jalan nih, pakai POST /chat buat ngobrol"}

@app.post("/scraper")
async def scraper_endpoint():
    loop = asyncio.get_event_loop()
    try:
        # jalanin run_scraper() di thread terpisah
        await loop.run_in_executor(None, dtsen_scraper.run_scraper)
        return {"status": "success", "message": "Scraper berhasil dijalankan"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
# Jalankan:
# uvicorn ai-backend.chatbot:app --host 0.0.0.0 --port 8000
