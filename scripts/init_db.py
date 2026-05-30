from app.database import engine, Base
from app.models.user import User
from app.models.raw_sleep_data import RawSleepData
from app.models.derived_sleep_data import DerivedSleepData
from app.models.user_stat import UserStat
from app.models.model_artifact import ModelArtifact

def init_db():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully!")

if __name__ == "__main__":
    init_db()
