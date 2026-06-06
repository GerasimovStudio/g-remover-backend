import os
import io
import zipfile
import datetime
import requests
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, Header, HTTPException, Depends, Request, Response
from sqlalchemy.orm import Session
from PIL import Image

from database import SessionLocal
import models
import replicate

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        if user.plan == "starter":
            if user.usage_reset and (datetime.datetime.now() - user.usage_reset).days >= 30:
                user.usage_count = 0
                user.usage_reset = datetime.datetime.now()
                db.commit()

            if user.usage_count >= 30:
                raise HTTPException(
                    status_code=429, 
                    detail="LIMIT_EXCEEDED: Вы израсходовали лимит 30 фото для Starter-тарифа."
                )
        return user.plan, user

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
        raise HTTPException(
            status_code=429, 
            detail="LIMIT_EXCEEDED: 5 бесплатных ежедневных попыток исчерпаны."
        )

    return "anonymous", guest


@router.post("/remove-bg")
async def remove_background(
    request: Request,
    file: UploadFile = File(...),
    background_color: Optional[str] = Form(None),
    background_file: UploadFile = File(None),
    x_user_email: Optional[str] = Header(None),
    email: Optional[str] = Form(None),                           # ИСПРАВЛЕНО: Теперь строго ждем из FormData
    db: Session = Depends(get_db)
):
    client_ip = request.client.host
    
    # Извлекаем email либо из хэдера, либо из формы
    final_email = x_user_email or email
    
    plan, db_record = check_and_update_limits(db, client_ip, final_email)

    try:
        file_bytes = await file.read()
        
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
        
        if background_file:
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
        raise HTTPException(status_code=500, detail=f"Ошибка нейросети: {str(e)}")

# ... (остальные эндпоинты оставляем как есть)