import os
import io
import zipfile
import datetime
import requests
from typing import List, Optional
from fastapi import FastAPI, APIRouter, UploadFile, File, Form, Header, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from PIL import Image

# Импортируем настройки базы данных и модели из твоего проекта
from database import engine, Base, SessionLocal
import models
import replicate

# Создаем таблицы в Supabase при запуске
Base.metadata.create_all(bind=engine)

app = FastAPI(title="gServices AI Background Remover", version="1.1.0")

# Настройка CORS — разрешаем абсолютно любые внешние запросы (включая Framer Preview)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Зависимость для получения сессии БД
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ОБРАБОТКИ ГРАФИКИ ---

def apply_background_color(image_bytes: bytes, hex_color: str) -> bytes:
    try:
        foreground = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        background = Image.new("RGBA", foreground.size, hex_color)
        combined = Image.alpha_composite(background, foreground)
        output = io.BytesIO()
        combined.convert("RGB").save(output, format="JPEG", quality=95)
        return output.getvalue()
    except Exception:
        return image_bytes

def apply_custom_background(foreground_bytes: bytes, background_bytes: bytes) -> bytes:
    try:
        foreground = Image.open(io.BytesIO(foreground_bytes)).convert("RGBA")
        background = Image.open(io.BytesIO(background_bytes)).convert("RGBA")
        background = background.resize(foreground.size, Image.Resampling.LANCZOS)
        combined = Image.alpha_composite(background, foreground)
        output = io.BytesIO()
        combined.convert("RGB").save(output, format="JPEG", quality=95)
        return output.getvalue()
    except Exception:
        return foreground_bytes

def check_and_update_limits(db: Session, client_ip: str, auth_email: Optional[str]) -> tuple[str, any]:
    today = datetime.date.today()

    if auth_email:
        user = db.query(models.User).filter(models.User.email == auth_email, models.User.is_active == True).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден в базе данных gServices")
        
        if user.plan == "starter":
            if user.usage_reset and (datetime.datetime.now() - user.usage_reset).days >= 30:
                user.usage_count = 0
                user.usage_reset = datetime.datetime.now()
                db.commit()

            if user.usage_count >= 30:
                raise HTTPException(status_code=429, detail="LIMIT_EXCEEDED: Starter лимит (30 фото) исчерпан.")
        return user.plan, user

    # Логика для гостя (анонима)
    guest = db.query(models.GuestSession).filter(models.GuestSession.session_id == client_ip).first()
    if not guest:
        guest = models.GuestSession(session_id=client_ip, usage_count=0)
        db.add(guest)
        db.commit()
        db.refresh(guest)

    if guest.created_at and guest.created_at.date() != today:
        guest.usage_count = 0
        guest.created_at = datetime.datetime.now()
        db.commit()

    if guest.usage_count >= 5:
        raise HTTPException(status_code=429, detail="LIMIT_EXCEEDED: Дневной лимит гостей (5 фото) исчерпан.")

    return "anonymous", guest

# --- ГЛАВНЫЕ ЭНДПОИНТЫ (ЯВНОЕ ОБЪЯВЛЕНИЕ ПУТЕЙ) ---

# Прописываем ВСЕ возможные вариации путей, чтобы исключить 404 при любых раскладах фронтенда
@app.post("/api/remove-bg")
@app.post("/api/remove-bg/")
@app.post("/remove-bg")
@app.post("/remove-bg/")
async def remove_background_core(
    request: Request,
    file: UploadFile = File(...),
    background_color: Optional[str] = Form(None),
    background_file: UploadFile = File(None),
    x_user_email: Optional[str] = Header(None), # Ловим из заголовков (Postman)
    email: Optional[str] = Form(None),           # Ловим из FormData (Framer)
    user_email: Optional[str] = None,            # Ловим из Query URL параметров (?user_email=...)
    db: Session = Depends(get_db)
):
    client_ip = request.client.host
    
    # Всеядный сборщик email: берём то, что оказалось заполнено
    final_email = x_user_email or email or user_email

    # Проверяем подписку и лимиты в Supabase
    plan, db_record = check_and_update_limits(db, client_ip, final_email)

    try:
        file_bytes = await file.read()
        
        # Запрос к нейросети Replicate (с фоллбэком на альтернативную модель)
        try:
            model = replicate.models.get("briaai/rmbg-1.5")
            target_version = model.versions.list()[0]
        except Exception:
            model = replicate.models.get("cjwbw/rembg")
            target_version = model.versions.list()[0]

        output = replicate.run(
            target_version,
            input={"image": io.BytesIO(file_bytes)}
        )
        
        img_data = requests.get(output).content
        
        # Наложение фонов, если они переданы
        if background_file and background_file.filename:
            bg_bytes = await background_file.read()
            img_data = apply_custom_background(img_data, bg_bytes)
            media_type = "image/jpeg"
        elif background_color:
            img_data = apply_background_color(img_data, background_color)
            media_type = "image/jpeg"
        else:
            media_type = "image/png"

        # Инкрементируем счётчик успешного использования в БД
        db_record.usage_count += 1
        db.commit()

        return Response(content=img_data, media_type=media_type)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка обработки ИИ: {str(e)}")


@app.get("/")
def health_check():
    return {"status": "online", "service": "gServices-AI-Core"}