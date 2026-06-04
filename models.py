from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    email         = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    plan          = Column(String, default="starter")   # starter | pro | studio
    usage_count   = Column(Integer, default=0)          # обработок за текущий месяц
    usage_reset   = Column(DateTime, default=func.now())# дата последнего сброса счётчика
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=func.now())


class GuestSession(Base):
    """Анонимные пользователи — 5 бесплатных попыток по session_id"""
    __tablename__ = "guest_sessions"

    id            = Column(Integer, primary_key=True, index=True)
    session_id    = Column(String, unique=True, index=True, nullable=False)
    usage_count   = Column(Integer, default=0)
    created_at    = Column(DateTime, default=func.now())
