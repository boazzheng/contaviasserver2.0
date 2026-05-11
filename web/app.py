import os
import sys
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

# Garante que o Python acha a raiz ANTES dos imports dos routers
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import init_db, Client, Project, User
from web import schemas
from database import get_db

# IMPORTAÇÃO DOS NOVOS MÓDULOS DE ROTA
from web.routers import admin, freelancer

# Inicializa o banco de dados
SessionLocal = init_db()

app = FastAPI(
    title="ContaVias Server 2.0",
    description="API para gestão de inferência de vídeos e alocação de freelancers",
    version="2.0.0"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(os.path.join(STATIC_DIR, "frames"), exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# REGISTRO DOS ROUTERS (A MÁGICA DA REFATORAÇÃO)
# ==========================================
app.include_router(admin.router)
app.include_router(freelancer.router)

# ==========================================
# ROTAS GLOBAIS DE SUPORTE
# ==========================================
@app.get("/")
def read_root():
    return {"status": "online", "message": "Bem-vindo ao ContaVias Server 2.0"}

@app.get("/clients")
def get_clients(db: Session = Depends(get_db)):
    clients = db.query(Client).all()
    return {"total": len(clients), "clients": clients}

@app.get("/projects")
def get_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).all()
    return {"total": len(projects), "projects": projects}

@app.post("/users", response_model=schemas.UserResponse)
def create_user(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == user_in.email).first():
        raise HTTPException(status_code=400, detail="Email já cadastrado.")
    
    novo_user = User(name=user_in.name, email=user_in.email, role="freelancer")
    db.add(novo_user)
    db.commit()
    db.refresh(novo_user)
    return novo_user

if __name__ == "__main__":
    import uvicorn
    print("Iniciando o servidor ContaVias 2.0...")
    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True)