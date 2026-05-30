from sqlalchemy import Column, String, Integer, Float, DateTime, Date, ForeignKey
from sqlalchemy.sql import func
import uuid
from app.database import Base

class DerivedSleepData(Base):
    __tablename__ = "derived_sleep_data"

    derived_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=False)
    raw_id = Column(String(36), ForeignKey("raw_sleep_data.raw_id"), nullable=False)
    date = Column(Date, nullable=False)
    
    # Derived Metrics
    sleep_eff = Column(Float)
    interrupt_index = Column(Float)
    consistency_7d = Column(Float)
    caff_gap_hours = Column(Float)
    caff_impact = Column(Float)
    screen_impact = Column(Float)
    act_gap_hours = Column(Float)
    
    # Scoring
    penalty = Column(Float, default=0.0)
    base_score = Column(Float)
    ml_score = Column(Float)
    final_score_raw = Column(Float)
    user_score = Column(Float) # Ground truth from user feedback
    user_class = Column(String(20)) # e.g., 'Good', 'Poor'
    final_score = Column(Integer) # Final rounded score
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
