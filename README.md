# Backend Development Guide

## Personalized Sleep Quality Analyzer – Backend Services

This document provides a comprehensive implementation guide for the backend services of the Personalized Sleep Quality Analyzer system. The backend is responsible for data ingestion, feature engineering, hybrid scoring (rule‑based + machine learning), incremental model training, insight generation, and serving a RESTful API consumed by the Flutter mobile application.

---

## 1. Overview

The backend implements the complete computational pipeline described in the methodology document. It is a modular, deterministic, and reproducible system designed to evolve from a rule‑based cold start into a fully personalized self‑supervised learning model.

### Core Responsibilities

| Responsibility                      | Description                                                                 |
|-------------------------------------|-----------------------------------------------------------------------------|
| User authentication & profile management | Signup, login, JWT issuance, profile storage                             |
| Raw data ingestion                  | Accept pre‑sleep and post‑sleep payloads from mobile app                     |
| Feature engineering                 | Compute derived metrics (TST, Sleep Efficiency, Bio_Score, etc.)             |
| Rule‑based analysis                 | Apply deterministic penalties and base scoring                               |
| Machine learning prediction         | Run regression/classification models (after cold start)                       |
| Incremental training orchestration  | Perform online `partial_fit` using user feedback as ground truth              |
| Insight generation                  | Correlate features with user scores to produce personalized recommendations  |
| Model artifact management           | Serialize and store scikit‑learn models in Cloudflare R2                      |
| Data persistence                    | Store raw data, derived data, and statistics in PostgreSQL (Supabase)         |

---

## 2. Technology Stack

All components are selected to operate within **free cloud tiers** for a thesis‑scale proof‑of‑concept.

| Component               | Technology                                                           | Purpose                                                                 |
|-------------------------|----------------------------------------------------------------------|-------------------------------------------------------------------------|
| Web Framework           | **FastAPI** (Python 3.10+)                                           | REST API, async support, automatic OpenAPI docs                          |
| Database                | **PostgreSQL** (via **Supabase** free tier)                           | Relational storage for users, raw/derived data, statistics               |
| Object Storage          | **Cloudflare R2** (10 GB free, zero egress)                           | Store serialized ML model files (`.pkl` / `.joblib`)                     |
| ML Library              | **scikit‑learn** (SGDRegressor, SGDClassifier for partial_fit)        | Online learning models                                                    |
| Background Tasks        | **FastAPI BackgroundTasks** or **Celery** (optional for heavier tasks) | Asynchronous training and insight computation                            |
| Deployment              | **Render Web Service** (free tier)                                    | Host FastAPI application                                                  |
| Authentication          | **JWT** (PyJWT)                                                       | Stateless authentication                                                   |
| Environment Variables   | **python‑dotenv**                                                      | Configuration management                                                   |
| HTTP Client (internal)  | **boto3** (for S3‑compatible R2)                                      | Upload/download model artifacts                                           |
| Data Validation         | **Pydantic** (built into FastAPI)                                     | Request/response schema validation                                        |

---

## 3. Project Structure

Adopt a layered architecture to separate concerns.

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                          # FastAPI application entry point
│   ├── config.py                        # Pydantic settings from .env
│   ├── database.py                      # SQLAlchemy engine & session
│   ├── models/                          # SQLAlchemy ORM models
│   │   ├── user.py
│   │   ├── raw_sleep_data.py
│   │   ├── derived_sleep_data.py
│   │   ├── user_stat.py
│   │   └── model_artifact.py
│   ├── schemas/                         # Pydantic request/response models
│   │   ├── auth.py
│   │   ├── profile.py
│   │   ├── sleep_data.py
│   │   └── analysis.py
│   ├── api/                             # Route handlers
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── profile.py
│   │   │   ├── sleep_data.py
│   │   │   ├── analysis.py
│   │   │   └── history.py
│   │   └── deps.py                      # Dependency injection (get_current_user, etc.)
│   ├── core/                            # Business logic modules
│   │   ├── feature_engineering.py       # Steps 2‑7 from methodology
│   │   ├── rule_analyzer.py             # Deterministic penalties & base score
│   │   ├── ml/
│   │   │   ├── predictor.py             # ML inference wrapper
│   │   │   ├── trainer.py               # Incremental/full training logic
│   │   │   └── model_manager.py         # Serialization & R2 upload/download
│   │   ├── scoring.py                   # Final score computation (blending)
│   │   ├── insights.py                  # Correlation analysis & recommendations
│   │   └── statistics.py                # Welford's algorithm for rolling stats
│   ├── services/                        # Higher‑level orchestration
│   │   ├── sleep_analysis_service.py    # Main daily pipeline
│   │   └── training_orchestrator.py     # Decides when to train/retrain
│   ├── utils/
│   │   ├── security.py                  # JWT creation/validation, password hashing
│   │   └── helpers.py                   # Date/time utilities, clamping
│   └── db/
│       ├── crud_user.py
│       ├── crud_sleep.py
│       └── crud_stats.py
├── tests/                               # Pytest unit & integration tests
├── scripts/
│   └── init_db.py                       # Create tables on Supabase
├── requirements.txt
├── Dockerfile                           # Optional containerization
├── render.yaml                          # Render Blueprint spec
└── .env.example
```

---

## 4. Configuration & Environment Variables

Create a `.env` file (never committed) with the following:

```env
# App
APP_ENV=development
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=10080   # 7 days

# Database (Supabase)
DATABASE_URL=postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres

# Cloudflare R2
R2_ACCESS_KEY_ID=your_r2_access_key
R2_SECRET_ACCESS_KEY=your_r2_secret_key
R2_ENDPOINT_URL=https://[accountid].r2.cloudflarestorage.com
R2_BUCKET_NAME=sleep-models

# Optional Redis (for caching)
REDIS_URL=redis://...
```

Load configuration using Pydantic `BaseSettings`:

```python
# app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_env: str = "development"
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080

    database_url: str

    r2_access_key_id: str
    r2_secret_access_key: str
    r2_endpoint_url: str
    r2_bucket_name: str

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## 5. Database Schema & ORM Models

Use **SQLAlchemy 2.0** with async support (optional) or standard synchronous sessions (simpler for scikit‑learn integration). The schema matches the ER diagram from Design.pdf.

### 5.1 User Table

```python
# app/models/user.py
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime
from sqlalchemy.sql import func
from app.database import Base

class User(Base):
    __tablename__ = "users"

    user_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email_verified = Column(Boolean, default=False)
    age = Column(Integer)
    gender = Column(String(10))
    weight_kg = Column(Float)
    height_cm = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

### 5.2 RAW_SLEEP_DATA Table

```python
# app/models/raw_sleep_data.py
class RawSleepData(Base):
    __tablename__ = "raw_sleep_data"

    raw_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=False)
    record_date = Column(Date, nullable=False)

    # Pre‑sleep fields (nullable initially)
    sleep_time = Column(Time)
    wake_time = Column(Time)
    awakenings = Column(Integer)
    sleep_latency_minutes = Column(Integer)
    naps = Column(Integer)
    hr_rest = Column(Integer)
    hrv = Column(Integer)
    body_temp = Column(Float)
    resp_rate = Column(Integer)
    caffeine_time = Column(Time)
    caffeine_mg = Column(Integer)
    alcohol_units = Column(Integer)
    water_liters = Column(Float)
    steps = Column(Integer)
    activity_intensity = Column(String(20))   # "low", "medium", "high"
    screen_minutes_before_bed = Column(Integer)
    stress = Column(Integer)   # 1‑10
    mood = Column(Integer)     # 1‑10
    room_temp = Column(Float)
    noise_db = Column(Integer)
    light_lux = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    user = relationship("User", back_populates="raw_sleep_data")
    derived = relationship("DerivedSleepData", back_populates="raw", uselist=False)
```

### 5.3 DERIVED_SLEEP_DATA Table

```python
# app/models/derived_sleep_data.py
class DerivedSleepData(Base):
    __tablename__ = "derived_sleep_data"

    derived_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=False)
    raw_id = Column(String(36), ForeignKey("raw_sleep_data.raw_id"), nullable=False)
    date = Column(Date, nullable=False)

    sleep_eff = Column(Float)
    interrupt_index = Column(Float)
    consistency_7d = Column(Float)
    caff_gap_hours = Column(Float)
    caff_impact = Column(Float)
    screen_impact = Column(Float)
    act_gap_hours = Column(Float)
    penalty = Column(Float, default=0.0)
    base_score = Column(Float)
    ml_score = Column(Float)
    final_score_raw = Column(Float)   # before clamping
    user_score = Column(Float)        # ground truth from user
    user_class = Column(String(10))   # "Good", "Moderate", "Poor"
    final_score = Column(Integer)     # clamped 0‑100
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    raw = relationship("RawSleepData", back_populates="derived")
```

### 5.4 USER_STAT Table (Metadata)

```python
# app/models/user_stat.py
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
    last_updated = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="stats")
```

### 5.5 MODEL_ARTIFACT Table

```python
# app/models/model_artifact.py
class ModelArtifact(Base):
    __tablename__ = "model_artifact"

    model_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=False)
    training_samples = Column(Integer, default=0)
    last_trained = Column(DateTime(timezone=True))
    regression_model_path = Column(String(255))   # R2 object key
    classifier_model_path = Column(String(255))
    current_learning_factor = Column(Float, default=0.0)

    user = relationship("User", back_populates="model_artifacts")
```

---

## 6. API Endpoints Specification

All endpoints are prefixed with `/api/v1` and require JWT authentication except `/auth/*`.

### 6.1 Authentication

| Method | Endpoint          | Description                                      |
|--------|-------------------|--------------------------------------------------|
| POST   | `/auth/signup`    | Register new user, returns JWT                    |
| POST   | `/auth/login`     | Authenticate, returns JWT                          |
| POST   | `/auth/refresh`   | Refresh access token (optional)                   |

**Request Body (Signup)**:
```json
{
  "email": "user@example.com",
  "password": "securepassword"
}
```

**Response**:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user_id": "uuid"
}
```

### 6.2 Profile Management

| Method | Endpoint       | Description                           |
|--------|----------------|---------------------------------------|
| GET    | `/profile`     | Get current user profile               |
| PUT    | `/profile`     | Update profile (age, gender, weight, height) |

### 6.3 Sleep Data Ingestion

| Method | Endpoint        | Description                                  |
|--------|-----------------|----------------------------------------------|
| POST   | `/sleep/raw`    | Submit pre‑sleep or post‑sleep partial data  |

**Request Body** (fields optional depending on time of day):
```json
{
  "record_date": "2026-04-23",
  "sleep_time": "23:30",
  "wake_time": "07:15",
  "awakenings": 2,
  "caffeine_mg": 150,
  ...
}
```

The endpoint should support **upsert** logic: if a record for `(user_id, record_date)` exists, update it; otherwise create. This allows the mobile app to send pre‑sleep data first, then update with post‑sleep data later.

### 6.4 Analysis & Scoring

| Method | Endpoint                | Description                                                       |
|--------|-------------------------|-------------------------------------------------------------------|
| GET    | `/sleep/analysis`       | Trigger analysis for current date and return sleep report          |
| POST   | `/sleep/feedback`       | Submit subjective `user_score` and `user_class` (if not in raw)    |

**GET `/sleep/analysis` Response**:
```json
{
  "date": "2026-04-23",
  "final_score": 82,
  "sleep_class": "Good",
  "personalization_active": true,
  "learning_factor": 0.35,
  "metrics": {
    "sleep_efficiency": 0.89,
    "tst_minutes": 420,
    "interrupt_index": 0.005,
    "consistency_7d": 0.92,
    "bio_score": 0.88,
    "mental_load": 0.3,
    "env_score": 0.75
  },
  "insights": [
    "Caffeine 3h before bed reduced your score by 8 points.",
    "Your heart rate variability was above normal (+1.2σ), improving recovery."
  ],
  "recommendations": [
    "Try to avoid caffeine after 4 PM.",
    "Consider a cooler room temperature; optimal is 20‑22°C."
  ]
}
```

### 6.5 History & Trends

| Method | Endpoint          | Description                               |
|--------|-------------------|-------------------------------------------|
| GET    | `/sleep/history`  | List historical sleep records (paginated) |
| GET    | `/sleep/trend`    | Last 7‑day scores for charting            |

---

## 7. Core Business Logic Implementation

### 7.1 Feature Engineering Module

Implement Steps 2‑7 from Methodology.pdf. Create a class that takes a `RawSleepData` ORM instance and returns a feature vector.

```python
# app/core/feature_engineering.py
import numpy as np
from datetime import datetime, timedelta
from app.models.raw_sleep_data import RawSleepData
from app.models.user_stat import UserStat
from app.core.statistics import compute_z_score

class FeatureEngineer:
    def __init__(self, raw: RawSleepData, user_stats: UserStat, recent_raw_records: list[RawSleepData]):
        self.raw = raw
        self.stats = user_stats
        self.recent = recent_raw_records   # last 7 days

    def compute_tib(self) -> float:
        if self.raw.sleep_time and self.raw.wake_time:
            # Convert to minutes, handle overnight sleep
            ...
        return 0.0

    def compute_tst(self) -> float:
        tib = self.compute_tib()
        latency = self.raw.sleep_latency_minutes or 0
        awake = self.raw.awakenings * 2  # simple estimate: 2 min per awakening
        return max(0, tib - latency - awake)

    def compute_sleep_efficiency(self) -> float:
        tib = self.compute_tib()
        return self.compute_tst() / tib if tib > 0 else 0.0

    def compute_interrupt_index(self) -> float:
        tst = self.compute_tst()
        return (self.raw.awakenings or 0) / tst if tst > 0 else 0.0

    def compute_consistency_7d(self) -> float:
        # Standard deviation of sleep_time over last 7 days
        sleep_times = [r.sleep_time.hour * 60 + r.sleep_time.minute for r in self.recent if r.sleep_time]
        if len(sleep_times) < 3:
            return 0.5   # default moderate consistency
        std_minutes = np.std(sleep_times)
        return max(0, 1 - (std_minutes / (24 * 60)))

    def compute_caff_impact(self) -> float:
        if self.raw.caffeine_time and self.raw.sleep_time:
            gap = (self.raw.sleep_time.hour * 60 + self.raw.sleep_time.minute) - \
                  (self.raw.caffeine_time.hour * 60 + self.raw.caffeine_time.minute)
            if gap < 0:
                gap += 24 * 60   # overnight
            gap_hours = gap / 60
            if gap_hours < 4:
                return 1.0
            elif gap_hours < 6:
                return 0.5
        return 0.1

    def compute_screen_impact(self) -> float:
        return (self.raw.screen_minutes_before_bed or 0) / 120.0

    def compute_bio_score(self) -> float:
        z_hr = compute_z_score(self.raw.hr_rest, self.stats.mean_hr_rest, self.stats.std_hr_rest)
        z_hrv = compute_z_score(self.raw.hrv, self.stats.mean_hrv, self.stats.std_hrv)
        z_temp = compute_z_score(self.raw.body_temp, self.stats.mean_body_temp, self.stats.std_body_temp)
        return 1 - (abs(z_hr) + abs(z_temp) - z_hrv) / 3

    def compute_mental_load(self) -> float:
        stress_impact = (self.raw.stress or 5) / 10.0
        mood_impact = 1 - ((self.raw.mood or 5) / 10.0)
        return (stress_impact + mood_impact) / 2

    def compute_env_score(self) -> float:
        temp_score = 1 - abs((self.raw.room_temp or 22) - 22) / 10
        noise_score = 1 - (self.raw.noise_db or 40) / 80
        light_score = 1 - (self.raw.light_lux or 0) / 300
        return (temp_score + noise_score + light_score) / 3

    def get_feature_vector(self) -> np.ndarray:
        return np.array([
            self.compute_tst(),
            self.compute_sleep_efficiency(),
            self.compute_interrupt_index(),
            self.compute_consistency_7d(),
            self.compute_caff_impact(),
            self.compute_screen_impact(),
            self.act_impact(),          # implement similar to methodology
            self.compute_bio_score(),
            self.compute_mental_load(),
            self.compute_env_score()
        ])
```

### 7.2 Rule‑Based Analyzer

```python
# app/core/rule_analyzer.py
class RuleAnalyzer:
    @staticmethod
    def compute_base_score(features: np.ndarray) -> float:
        # weights: TST(0.25), SleepEff(0.20), Consistency(0.15), Interrupt(0.15), MentalLoad(0.15), BioScore(0.10)
        weights = np.array([0.25, 0.20, 0.15, 0.15, 0.15, 0.10])
        # Normalize TST to 0‑1 (assume ideal 420‑540 min)
        tst_norm = min(features[0] / 480, 1.0)
        scaled_features = np.array([
            tst_norm,
            features[1],                     # SleepEff already 0‑1
            features[3],                     # Consistency
            1 - features[2],                 # Interrupt inverse
            1 - features[8],                 # Mental Load inverse
            features[7]                      # BioScore
        ])
        return np.dot(weights, scaled_features)

    @staticmethod
    def compute_penalty(raw: RawSleepData, sleep_eff: float) -> float:
        penalty = 0.0
        # Caffeine gap penalty
        if raw.caffeine_time and raw.sleep_time:
            gap = (raw.sleep_time.hour * 60 + raw.sleep_time.minute) - \
                  (raw.caffeine_time.hour * 60 + raw.caffeine_time.minute)
            if gap < 0:
                gap += 24 * 60
            if gap / 60 < 4:
                penalty += 8
        # Stress penalty
        if raw.stress and raw.stress > 7:
            penalty += 6
        # Sleep efficiency penalty
        if sleep_eff < 0.75:
            penalty += 10
        # Awakenings penalty
        if raw.awakenings and raw.awakenings > 4:
            penalty += 6
        return penalty
```

### 7.3 Machine Learning Models

Use scikit‑learn's `SGDRegressor` and `SGDClassifier` which support `partial_fit` for online learning.

```python
# app/core/ml/model_manager.py
import joblib
import boto3
from io import BytesIO
from app.config import settings

class ModelManager:
    def __init__(self):
        self.s3 = boto3.client(
            's3',
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key
        )
        self.bucket = settings.r2_bucket_name

    def save_model(self, user_id: str, model_type: str, model_obj) -> str:
        """Save model to R2 and return object key."""
        buffer = BytesIO()
        joblib.dump(model_obj, buffer)
        buffer.seek(0)
        key = f"models/{user_id}/{model_type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.joblib"
        self.s3.upload_fileobj(buffer, self.bucket, key)
        return key

    def load_model(self, object_key: str):
        """Load model from R2."""
        buffer = BytesIO()
        self.s3.download_fileobj(self.bucket, object_key, buffer)
        buffer.seek(0)
        return joblib.load(buffer)
```

**Predictor**:

```python
# app/core/ml/predictor.py
class MLPredictor:
    def predict_score(self, user_id: str, features: np.ndarray) -> float:
        artifact = db.query(ModelArtifact).filter_by(user_id=user_id).first()
        if not artifact or not artifact.regression_model_path:
            return None   # fallback to base score
        model = model_manager.load_model(artifact.regression_model_path)
        return float(model.predict(features.reshape(1, -1))[0])

    def predict_class(self, user_id: str, features: np.ndarray) -> str:
        ...
```

**Trainer**:

```python
# app/core/ml/trainer.py
from sklearn.linear_model import SGDRegressor, SGDClassifier

class IncrementalTrainer:
    def __init__(self):
        self.regressor = SGDRegressor(loss='squared_error', penalty='l2', alpha=0.0001, max_iter=1000, tol=1e-3)
        self.classifier = SGDClassifier(loss='log_loss', penalty='l2', alpha=0.0001)

    def partial_fit(self, X: np.ndarray, y_score: float, y_class: str):
        # For classifier, map class to int
        class_map = {"Poor": 0, "Moderate": 1, "Good": 2}
        y_class_int = class_map.get(y_class, 1)
        self.regressor.partial_fit(X.reshape(1, -1), [y_score])
        self.classifier.partial_fit(X.reshape(1, -1), [y_class_int], classes=[0,1,2])
```

### 7.4 Final Score Computation (Blending)

Implement Step 16 from methodology.

```python
# app/core/scoring.py
def compute_final_score(
    base_score: float,
    ml_score: float,
    penalty: float,
    learning_factor: float,
) -> int:
    blended = (1 - learning_factor) * base_score + learning_factor * ml_score
    raw = (blended * 100) - penalty
    return max(0, min(100, int(round(raw))))
```

### 7.5 Statistics (Welford's Online Algorithm)

Used to update rolling means and standard deviations efficiently.

```python
# app/core/statistics.py
def update_welford(existing_mean, existing_std, existing_n, new_value):
    n = existing_n + 1
    delta = new_value - existing_mean
    mean = existing_mean + delta / n
    m2 = (existing_std ** 2) * existing_n + delta * (new_value - mean)
    std = (m2 / n) ** 0.5 if n > 1 else 0.0
    return mean, std, n
```

---

## 8. Main Sleep Analysis Service

Orchestrates the entire daily pipeline.

```python
# app/services/sleep_analysis_service.py
class SleepAnalysisService:
    def __init__(self, db: Session, user_id: str, date: date):
        self.db = db
        self.user_id = user_id
        self.date = date

    def execute(self):
        # 1. Retrieve raw data for date
        raw = self.db.query(RawSleepData).filter_by(user_id=self.user_id, record_date=self.date).first()
        if not raw:
            raise ValueError("No raw data for this date")

        # 2. Fetch user stats and recent raw records
        stats = self.db.query(UserStat).filter_by(user_id=self.user_id).first()
        recent_raw = self.db.query(RawSleepData).filter(
            RawSleepData.user_id == self.user_id,
            RawSleepData.record_date < self.date
        ).order_by(RawSleepData.record_date.desc()).limit(7).all()

        # 3. Feature engineering
        engineer = FeatureEngineer(raw, stats, recent_raw)
        features = engineer.get_feature_vector()

        # 4. Rule‑based base score & penalty
        base_score = RuleAnalyzer.compute_base_score(features)
        sleep_eff = engineer.compute_sleep_efficiency()
        penalty = RuleAnalyzer.compute_penalty(raw, sleep_eff)

        # 5. ML prediction (if models exist)
        ml_score = None
        sleep_class = None
        learning_factor = 0.0
        artifact = self.db.query(ModelArtifact).filter_by(user_id=self.user_id).first()
        if artifact and artifact.training_samples >= 14:
            learning_factor = min(1.0, artifact.training_samples / 60.0)
            predictor = MLPredictor()
            ml_score = predictor.predict_score(self.user_id, features)
            sleep_class = predictor.predict_class(self.user_id, features)
        else:
            ml_score = base_score
            sleep_class = self._rule_based_classification(features)

        # 6. Final score
        final_score = compute_final_score(base_score, ml_score, penalty, learning_factor)

        # 7. Store derived data
        derived = DerivedSleepData(
            user_id=self.user_id,
            raw_id=raw.raw_id,
            date=self.date,
            sleep_eff=sleep_eff,
            interrupt_index=features[2],
            consistency_7d=features[3],
            caff_impact=features[4],
            screen_impact=features[5],
            penalty=penalty,
            base_score=base_score,
            ml_score=ml_score,
            final_score_raw=(base_score + ml_score)/2 * 100 - penalty,
            final_score=final_score,
            user_score=raw.user_score,   # may be None initially
            user_class=raw.user_class,
        )
        self.db.add(derived)
        self.db.commit()

        # 8. Update user statistics (Welford)
        self._update_statistics(raw)

        # 9. Trigger incremental training as background task
        if raw.user_score is not None:
            BackgroundTasks.add_task(self._train_model, features, raw.user_score, raw.user_class)

        return derived

    def _train_model(self, features, user_score, user_class):
        # Incremental training logic
        trainer = IncrementalTrainer()
        artifact = self.db.query(ModelArtifact).filter_by(user_id=self.user_id).first()
        # Load existing models, partial_fit, save back to R2, update DB
        ...
```

---

## 9. Background Tasks & Training Orchestrator

FastAPI `BackgroundTasks` can handle lightweight async jobs. For full retraining (every 30 days), consider a scheduled task using `APScheduler` or a separate Render Cron Job.

```python
# app/services/training_orchestrator.py
class TrainingOrchestrator:
    @staticmethod
    async def check_and_full_retrain(user_id: str):
        # Called periodically (e.g., every 30 days)
        # Query all data for user, fit new models, update R2 and DB
        ...
```

---

## 10. Insight Engine

Correlate features with historical `user_score` to generate personalized insights.

```python
# app/core/insights.py
def generate_insights(user_id: str, current_features: np.ndarray) -> list[str]:
    # Fetch last 30 days of features + user_score
    # Compute Pearson correlation for each feature
    # Identify features with strong negative correlation to score
    insights = []
    if caff_corr < -0.3:
        insights.append("Caffeine close to bedtime consistently lowers your sleep quality.")
    if screen_corr < -0.3:
        insights.append("Screen time before bed is associated with poorer sleep.")
    # Add specific insights based on today's values
    if current_features[4] == 1.0:   # caff_impact
        insights.append("Tonight's caffeine within 4h of bed may reduce your score.")
    return insights
```

---

## 11. Deployment on Render

### 11.1 Render Blueprint (`render.yaml`)

```yaml
services:
  - type: web
    name: sleep-analyzer-api
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: sleep-db
          property: connectionString
      - key: SECRET_KEY
        generateValue: true
      - key: R2_ACCESS_KEY_ID
        sync: false
      - key: R2_SECRET_ACCESS_KEY
        sync: false
      - key: R2_ENDPOINT_URL
        sync: false
      - key: R2_BUCKET_NAME
        sync: false

databases:
  - name: sleep-db
    plan: free   # Render PostgreSQL free tier (90 days, then upgrade or migrate)
```

Alternatively, use **Supabase** for a persistent free PostgreSQL database. Provide `DATABASE_URL` manually in Render environment variables.

### 11.2 Cold Start & Database Initialization

Create tables on Supabase using SQLAlchemy's `Base.metadata.create_all(engine)` or a migration tool like Alembic.

---

## 12. Security Implementation

- **Password Hashing**: Use `passlib` with bcrypt.
- **JWT**: Use `python-jose` for token creation and validation.
- **CORS**: Configure FastAPI CORS middleware to allow only the Flutter app's origin.
- **Row‑Level Security**: Enforce `user_id` filtering in all database queries (e.g., `filter(User.user_id == current_user_id)`).
- **Input Validation**: Pydantic models validate all request bodies.

```python
# app/api/deps.py
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from app.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise credentials_exception
    return user
```

---

## 13. Testing Strategy

- **Unit tests**: Test feature engineering calculations, scoring formulas.
- **Integration tests**: Use `TestClient` to test API endpoints with a test database (SQLite in‑memory).
- **Mock external services**: Mock boto3 for R2 and Supabase calls.

---

## 14. Conclusion

This backend implementation guide provides a complete blueprint for building the Personalized Sleep Quality Analyzer API. By following the modular structure, leveraging free cloud tiers, and implementing the hybrid scoring and incremental learning algorithms described, developers can create a fully functional, self‑supervised sleep analysis system ready for integration with the Flutter mobile app.

The backend is designed to be scalable, maintainable, and compliant with the methodology's requirements for personalization, explainability, and human‑in‑the‑loop learning.