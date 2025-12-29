import os

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://maconly:maconly@db:5432/maconly_db",
)
