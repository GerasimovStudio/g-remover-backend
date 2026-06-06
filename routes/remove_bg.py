import os
import io
import zipfile
import datetime
import requests
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, Header, HTTPException, Depends, Request, Response
from sqlalchemy.orm import Session
from PIL import Image

# Импортируем сессию базы данных и модели из корня проекта
from database import SessionLocal
import models
import replicate

router = APIRouter()

# Зависимость для безопасного подключения к базе данных
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def apply_background_color(image_bytes: bytes, hex_color: str) -> bytes:
    """Вспомогательная функция: подкладывает сплошной цвет под вырезанный PNG"""
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
    """Вспомогательная функция: берет кастомное фото пользователя и ставит его на фон"""
    try:
        foreground = Image.open(io.BytesIO(foreground_bytes)).convert("RGBA")
        background = Image.open(io.BytesIO(background_bytes)).convert("RGBA")
        
        # Умное масштабирование: подгоняем размер фонового фото под размер вырезанного объекта
        background = background.resize(foreground.size, Image.Resampling.LANCZOS)
        
        # Склеиваем слои: фон снизу, объект сверху
        combined = Image.alpha_composite(background, foreground)
        
        output = io.BytesIO()
        combined.convert("RGB").save(output, format="JPEG", quality=95)
        return output.getvalue()
    except Exception:
        return foreground_bytes


def check_and_update_limits(db: Session, client_ip: str, auth_email: Optional[str]) -> tuple[str, any]:
    """
    Проверяет лимиты согласно тарифной сетке gServices:
    - Аноним: 5 в день
    - Starter: 30 в месяц
    - Pro / Studio: Безлимит
    """
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

    if guest.usage_count