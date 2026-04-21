from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    # Import all models to ensure they're registered with Base
    from app.core import models  # v1 models
    from app.core import models_v2  # v2 models
    from app.core import models_v3  # v3 models
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
