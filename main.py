from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base

# ⚠️ ВАЖНО: Принудительно импортируем файл с таблицами, 
# чтобы Python прочитал его ДО создания базы данных
import models 

# 🔍 Эта строчка напечатает в терминал список таблиц, которые увидел Python
print("====== PYTHON СЕЙЧАС УВИДЕЛ ТАБЛИЦЫ:", list(Base.metadata.tables.keys()), "======")

# Создаём таблицы в облаке Supabase при старте
Base.metadata.create_all(bind=engine)

app = FastAPI(title="g-Remover API", version="1.0.0")

# CORS — разрешаем запросы с Framer сайта
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене замени на свой домен Framer
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Импортируем роуты
from routes import remove_bg, users
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(remove_bg.router, prefix="/api", tags=["remove-bg"])

@app.get("/")
def root():
    return {"status": "ok", "service": "g-Remover API"}