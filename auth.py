from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db
from models import User
import os

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-please")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 дней

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/users/login", auto_error=False)

# Лимиты обработок в месяц по тарифам
PLAN_LIMITS = {
    "starter":  50,
    "pro":      None,   # безлимит
    "studio":   None,   # безлимит
}

GUEST_LIMIT = 5  # бесплатных попыток без регистрации


def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User | None:
    """Возвращает пользователя если токен валиден, иначе None (гость)."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if not email:
            return None
    except JWTError:
        return None
    return db.query(User).filter(User.email == email).first()

def require_auth(user: User | None = Depends(get_current_user)) -> User:
    """Зависимость для защищённых эндпоинтов."""
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user

def check_and_increment_user_limit(user: User, db: Session):
    """Проверяет и увеличивает счётчик для авторизованного пользователя."""
    limit = PLAN_LIMITS.get(user.plan)

    # Сброс счётчика если прошёл месяц
    now = datetime.utcnow()
    if user.usage_reset and (now - user.usage_reset).days >= 30:
        user.usage_count = 0
        user.usage_reset = now
        db.commit()

    if limit is not None and user.usage_count >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Лимит исчерпан ({limit} обработок/мес). Перейдите на Pro тариф."
        )

    user.usage_count += 1
    db.commit()
