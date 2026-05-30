from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime
from sqlalchemy.sql import func
import uuid
from app.database import Base

class User(Base):
    __tablename__ = "users"

    user_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email_verified = Column(Boolean, default=False)
    full_name = Column(String(120))
    age = Column(Integer)
    gender = Column(String(10))
    weight_kg = Column(Float)
    height_cm = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
