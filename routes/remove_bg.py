from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Header
from fastapi.responses import Response
from sqlalchemy.orm import Session
from database import get_db
from models import User, GuestSession
from auth import get_current_user, check_and_increment_user_limit, GUEST_LIMIT
from PIL import Image
import io
import uuid

# ИМПОРТИРУЕМ: Добавили new_session для переключения ИИ-моделей
from rembg import remove, new_session 

router = APIRouter()

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_TYPES = {"image/jpeg", "image/jpg", "image/png"}

# --- Инициализация ИИ-модели высокого качества ---
# При старте сервера rembg проверит модель в кэше Mac. Если её нет, он сам скачает её.
# "isnet-general-use" — выдает шикарное качество и работает быстро.
# (Альтернатива для теста супер-качества: "birefnet-general", но она весит больше)
ai_session = new_session("isnet-general-use")


@router.post("/remove-bg")
async def remove_background(
    file: UploadFile = File(...),
    x_session_id: str | None = Header(default=None),  # для гостей
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    # --- Валидация файла ---
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Только JPG, JPEG или PNG")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Файл больше 10 МБ")

    # --- Лимиты ---
    if current_user:
        # Авторизованный пользователь
        check_and_increment_user_limit(current_user, db)
    else:
        # Гость — по session_id
        if not x_session_id:
            x_session_id = str(uuid.uuid4())  # клиент должен хранить и передавать его

        guest = db.query(GuestSession).filter(
            GuestSession.session_id == x_session_id
        ).first()

        if not guest:
            guest = GuestSession(session_id=x_session_id, usage_count=0)
            db.add(guest)
            db.commit()
            db.refresh(guest)

        if guest.usage_count >= GUEST_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=f"Бесплатный лимит ({GUEST_LIMIT} попыток) исчерпан. Зарегистрируйтесь бесплатно!"
            )

        guest.usage_count += 1
        db.commit()

    # --- Удаление фона с помощью продвинутой модели ---
    try:
        input_image = Image.open(io.BytesIO(contents))
        
        # Передаем нашу качественную сессию ai_session в функцию remove
        output_image = remove(input_image, session=ai_session)

        output_buffer = io.BytesIO()
        output_image.save(output_buffer, format="PNG")
        output_buffer.seek(0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка обработки: {str(e)}")

    remaining = None
    if not current_user:
        guest_refreshed = db.query(GuestSession).filter(
            GuestSession.session_id == x_session_id
        ).first()
        remaining = GUEST_LIMIT - (guest_refreshed.usage_count if guest_refreshed else 0)

    headers = {}
    if remaining is not None:
        headers["X-Remaining-Uses"] = str(remaining)
    if not current_user:
        headers["X-Session-Id"] = x_session_id

    return Response(
        content=output_buffer.read(),
        media_type="image/png",
        headers=headers,
    )


@router.get("/guest-status")
def guest_status(
    x_session_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Проверить сколько бесплатных попыток осталось у гостя."""
    if not x_session_id:
        return {"remaining": GUEST_LIMIT, "session_id": None}

    guest = db.query(GuestSession).filter(
        GuestSession.session_id == x_session_id
    ).first()

    used = guest.usage_count if guest else 0
    return {
        "remaining": max(0, GUEST_LIMIT - used),
        "used": used,
        "limit": GUEST_LIMIT,
    }