import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 1. Pega o caminho absoluto da pasta onde este arquivo (database.py) está (/dev/web)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 2. Volta uma pasta e entra na db (/dev/db)
DB_DIR = os.path.join(os.path.dirname(BASE_DIR), "db")

# 3. Garante que a pasta 'db' existe (se você a deletou sem querer, o Python recria)
os.makedirs(DB_DIR, exist_ok=True)

# 4. Monta o caminho completo do arquivo do banco
DB_PATH = os.path.join(DB_DIR, "contavias.sqlite3.db")

# 5. Configura a URL do SQLAlchemy com o caminho absoluto
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

# O resto continua igual...
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()