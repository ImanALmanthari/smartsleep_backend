from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
import uuid
from app.database import Base

class ModelArtifact(Base):
    __tablename__ = "model_artifact"

    model_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=False, unique=True)
    training_samples = Column(Integer, default=0)
    last_trained = Column(DateTime(timezone=True))
    regression_model_path = Column(String(255))
    classifier_model_path = Column(String(255))
    current_learning_factor = Column(Float, default=0.0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
