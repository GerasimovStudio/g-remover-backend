import os
import io
import zipfile
import datetime
import requests
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from PIL import Image

# Импортируем подключение к базе и модели из корня твоего проекта
from database import engine, Base, SessionLocal
import models
import replicate

# Инициализируем таблицы в Supabase при старте приложения
Base.metadata.create_all(bind=engine)

app = FastAPI(title="gServices AI Engine Premium", version="1.5.0")

# Настройка CORS — открываем доступ для Framer Preview и продакшна
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Зависимость сессии базы данных
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ОБРАБОТКИ ИЗОБРАЖЕНИЙ ---

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

    # Если email передано, проверяем его в базе данных Supabase
    if auth_email:
        user = db.query(models.User).filter(models.User.email == auth_email, models.User.is_active == True).first()
        if user:
            if user.plan == "starter":
                if user.usage_reset and (datetime.datetime.now() - user.usage_reset).days >= 30:
                    user.usage_count = 0
                    user.usage_reset = datetime.datetime.now()
                    db.commit()

                if user.usage_count >= 30:
                    raise HTTPException(status_code=429, detail="LIMIT_EXCEEDED: Лимит тарифа Starter исчерпан.")
            return user.plan, user
        
        # Если юзер не найден (например, тестовый во Framer), мягко спускаем на лимиты гостя без ошибки 404

    # Логика для гостя (анонимная сессия по IP)
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
        raise HTTPException(status_code=429, detail="LIMIT_EXCEEDED: Дневной лимит гостя исчерпан.")

    return "anonymous", guest

# --- ЖЕЛЕЗОБЕТОННЫЕ ЭНДПОИНТЫ ДЛЯ ФРОНТЕНДА ---

@app.post("/api/remove-bg")
@app.post("/api/remove-bg/")
async def remove_background(
    request: Request,
    file: UploadFile = File(...),
    background_color: Optional[str] = Form(None),
    background_file: UploadFile = File(None),
    x_user_email: Optional[str] = Header(None),
    email: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    client_ip = request.client.host
    final_email = x_user_email or email
    plan, db_record = check_and_update_limits(db, client_ip, final_email)

    try:
        file_bytes = await file.read()
        
        # Умный каскадный выбор ИИ-модели для идеального качества контуров
        try:
            # Шаг 1: Пробуем премиальный BiRefNet
            model = replicate.models.get("zhengpeng7/birefnet")
            target_version = model.versions.list()[0]
        except Exception:
            try:
                # Шаг 2: Запасной вариант, если первый перегружен — BRIA RMBG-1.5
                model = replicate.models.get("briaai/rmbg-1.5")
                target_version = model.versions.list()[0]
            except Exception:
                # Шаг 3: Крайний случай — базовая модель rembg
                model = replicate.models.get("cjwbw/rembg")
                target_version = model.versions.list()[0]

        # Отправляем картинку в Replicate
        output = replicate.run(target_version, input={"image": io.BytesIO(file_bytes)})
        img_data = requests.get(output).content
        
        # Проверяем, нужно ли наложить цвет или кастомный фон
        if background_file and background_file.filename:
            bg_bytes = await background_file.read()
            img_data = apply_custom_background(img_data, bg_bytes)
            media_type = "image/jpeg"
        elif background_color:
            img_data = apply_background_color(img_data, background_color)
            media_type = "image/jpeg"
        else:
            media_type = "image/png"

        db_record.usage_count += 1
        db.commit()
        return Response(content=img_data, media_type=media_type)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка ИИ: {str(e)}")


@app.post("/api/enhance-image")
@app.post("/api/enhance-image/")
async def enhance_image(
    request: Request,
    file: UploadFile = File(...),
    x_user_email: Optional[str] = Header(None),
    email: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    client_ip = request.client.host
    final_email = x_user_email or email
    plan, _ = check_and_update_limits(db, client_ip, final_email)

    try:
        file_bytes = await file.read()
        try:
            model = replicate.models.get("sczhou/codeformer")
            target_version = model.versions.list()[0]
        except Exception:
            target_version = "7de2ac439e34d6d99cd94ef191509c07b8b7d345f6624a02701c5b00224b13a2"
        
        output = replicate.run(
            target_version,
            input={
                "image": io.BytesIO(file_bytes),
                "codeformer_fidelity": 0.7,
                "background_enhance": True,
                "face_upsample": True,
                "upscale": 2
            }
        )
        img_data = requests.get(output).content
        return Response(content=img_data, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка улучшения: {str(e)}")


@app.post("/api/batch-remove-bg")
@app.post("/api/batch-remove-bg/")
async def batch_remove_background(
    request: Request,
    files: List[UploadFile] = File(...),
    x_user_email: Optional[str] = Header(None),
    email: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    client_ip = request.client.host
    final_email = x_user_email or email
    plan, db_record = check_and_update_limits(db, client_ip, final_email)

    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Максимум 10 файлов за раз.")

    zip_buffer = io.BytesIO()
    
    # Подготавливаем BiRefNet для пакетной резки
    try:
        model = replicate.models.get("zhengpeng7/birefnet")
        target_version = model.versions.list()[0]
    except Exception:
        model = replicate.models.get("briaai/rmbg-1.5")
        target_version = model.versions.list()[0]

    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for index, file in enumerate(files):
            try:
                file_bytes = await file.read()
                output = replicate.run(target_version, input={"image": io.BytesIO(file_bytes)})
                img_data = requests.get(output).content
                zip_file.writestr(f"g_remover_{index + 1}.png", img_data)
                db_record.usage_count += 1
            except Exception:
                continue

    db.commit()
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=g_remover_batch.zip"}
    )


# Безопасный импорт дополнительных роутов пользователей (если они есть)
try:
    from routes import users
    app.include_router(users.router, prefix="/api/users", tags=["users"])
except Exception:
    pass

@app.get("/")
def root():
    return {"status": "online", "service": "gServices-AI-Engine-BiRefNet-Active"}