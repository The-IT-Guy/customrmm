from __future__ import annotations
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.settings import settings

class Base(DeclarativeBase):
    pass

engine = create_engine(
    settings.DB_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if settings.DB_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
