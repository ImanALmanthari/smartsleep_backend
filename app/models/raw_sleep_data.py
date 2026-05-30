from sqlalchemy import Column, String, Integer, Float, DateTime, Date, Time, ForeignKey
from sqlalchemy.sql import func
import uuid
from app.database import Base

class RawSleepData(Base):
    __tablename__ = "raw_sleep_data"

    raw_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=False)
    record_date = Column(Date, nullable=False)
    
    # Sleep timing
    sleep_time = Column(Time)
    wake_time = Column(Time)
    awakenings = Column(Integer)
    sleep_latency_minutes = Column(Integer)
    naps = Column(Integer)
    
    # Bio-metrics
    hr_rest = Column(Integer)
    hrv = Column(Integer)
    body_temp = Column(Float)
    resp_rate = Column(Integer)
    
    # Lifestyle
    caffeine_time = Column(Time)
    caffeine_mg = Column(Integer)
    alcohol_units = Column(Integer)
    water_liters = Column(Float)
    steps = Column(Integer)
    activity_intensity = Column(String(20))
    screen_minutes_before_bed = Column(Integer)
    
    # Subjective
    stress = Column(Integer)
    mood = Column(Integer)
    
    # Environment
    room_temp = Column(Float)
    noise_db = Column(Integer)
    light_lux = Column(Integer)
    
    pre_sleep_submitted_at = Column(DateTime(timezone=True))
    post_sleep_submitted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
