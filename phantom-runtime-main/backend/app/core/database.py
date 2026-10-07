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
    _ensure_chain_unique_constraint()


_CHAIN_UNIQUE_SQL = """
DO $$
BEGIN
  IF to_regclass('public.events_v3') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_events_v3_entity_block') THEN
    IF EXISTS (SELECT 1 FROM public.events_v3 GROUP BY entity_id, block_index HAVING count(*) > 1) THEN
      RAISE WARNING 'events_v3 has forked chains (duplicate entity_id, block_index); '
                    'uq_events_v3_entity_block NOT added. Resolve the duplicates, then restart.';
    ELSE
      ALTER TABLE public.events_v3
        ADD CONSTRAINT uq_events_v3_entity_block UNIQUE (entity_id, block_index);
    END IF;
  END IF;
END $$;
"""


def _ensure_chain_unique_constraint():
    """create_all never alters an existing table, so databases created before the constraint
    existed get it here. Skips (with a warning) instead of failing startup if forks already exist."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(_CHAIN_UNIQUE_SQL))
