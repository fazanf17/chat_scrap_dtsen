import sys
import os

# --- set environment kalau perlu ---
os.environ['APP_ENV'] = 'production'

# --- import FastAPI app dari chatbot.py ---
from chatbot import app

# --- bungkus FastAPI (ASGI) jadi WSGI ---
from asgiref.wsgi import WsgiToAsgi
application = WsgiToAsgi(app)
