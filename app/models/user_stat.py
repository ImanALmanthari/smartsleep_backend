from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base

class UserStat(Base):
    __tablename__ = "user_stat"

    user_id = Column(String(36), ForeignKey("users.user_id"), primary_key=True)
    mean_hr_rest = Column(Float, default=0.0)
    std_hr_rest = Column(Float, default=0.0)
    mean_hrv = Column(Float, default=0.0)
    std_hrv = Column(Float, default=0.0)
    mean_body_temp = Column(Float, default=0.0)
    std_body_temp = Column(Float, default=0.0)
    sample_count = Column(Integer, default=0)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
