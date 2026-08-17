import os

import redis
from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

# Deterministic names for constraints we do NOT name explicitly — without this
# Postgres auto-names them and a later migration cannot reliably drop them.
#
# Only fk and pk are listed. Checks, uniques and indexes are already named
# explicitly at every call site; adding them here would double the prefix
# (ck_carts_ck_carts_currency_egp), because the convention substitutes the name
# we already supplied into its own template.
NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}

Base = declarative_base(metadata=MetaData(naming_convention=NAMING_CONVENTION))

Engine = create_engine(os.getenv("DB_URL"), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=Engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    db=0,
    decode_responses=True,
)
