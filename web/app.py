import os
import sys
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload

from fastapi import FastAPI, Depends, HTTPException, Request # <-- Adicione o Request aqui
from fastapi.templating import Jinja2Templates # <-- Nova importação
from fastapi.responses import HTMLResponse

# Garante que o Python ache a pasta 'web' corretamente
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.models import init_db, Client, Project, Video, VideoStatus
from web import schemas

# Inicializa o banco de dados e cria a "fábrica" de sessões
SessionLocal = init_db()

app = FastAPI(
    title="ContaVias Server 2.0",
    description="API para gestão de inferência de vídeos e alocação de freelancers (Padrão DNIT)",
    version="2.0.0"
)

# Configuração do renderizador de HTML
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# Configuração de CORS (Permite que o frontend se comunique com esta API)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Em produção, mudaremos para o domínio exato
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependência para injeção do Banco de Dados nas rotas
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================================
# ROTAS DE TESTE E VALIDAÇÃO
# ==========================================

@app.get("/")
def read_root():
    """Health check simples para ver se a API está no ar."""
    return {"status": "online", "message": "Bem-vindo ao ContaVias Server 2.0"}

@app.get("/clients")
def get_clients(db: Session = Depends(get_db)):
    """Busca todos os clientes no banco de dados para testar a conexão."""
    clients = db.query(Client).all()
    return {"total": len(clients), "clients": clients}

@app.get("/projects")
def get_projects(db: Session = Depends(get_db)):
    """Busca todos os projetos para sabermos quais IDs usar."""
    projects = db.query(Project).all()
    return {"total": len(projects), "projects": projects}

# ==========================================
# ROTAS DA FILA DE STAGING (ÉPICO 1)
# ==========================================

# 1. ROTA GET (Usada pelo Dashboard HTML para mostrar a tabela)
@app.get("/videos/staged")
def get_staged_videos(db: Session = Depends(get_db)):
    """Retorna os vídeos na Fila de Staging com os dados de Cliente e Projeto."""
    videos = db.query(Video).options(
        joinedload(Video.project).joinedload(Project.client)
    ).filter(Video.status == "staged").all()
    
    return {"total": len(videos), "videos": videos}


# 2. ROTA POST (Usada pelo Robô do Drive para injetar vídeos novos)
@app.post("/videos/staged", response_model=schemas.VideoResponse, status_code=201)
def create_staged_video(video_in: schemas.VideoCreate, db: Session = Depends(get_db)):
    """Recebe o aviso do Drive. Auto-cadastra Cliente/Projeto e barra duplicatas."""
    
    # 1. Busca ou cria o Cliente
    client = db.query(Client).filter(Client.name == video_in.client_name).first()
    if not client:
        client = Client(name=video_in.client_name)
        db.add(client)
        db.commit()
        db.refresh(client)

    # 2. Busca ou cria o Projeto
    project = db.query(Project).filter(
        Project.name == video_in.project_name, 
        Project.client_id == client.id
    ).first()
    
    if not project:
        project = Project(name=video_in.project_name, client_id=client.id)
        db.add(project)
        db.commit()
        db.refresh(project)

    # ==========================================
    # NOVO: ESCUDO ANTI-DUPLICIDADE
    # ==========================================
    # 3. Verifica se ESTE arquivo já existe NESTE projeto
    video_existente = db.query(Video).filter(
        Video.original_filename == video_in.original_filename,
        Video.project_id == project.id
    ).first()

    if video_existente:
        # Se já existe, devolvemos um erro 409 (Conflict) avisando o robô
        raise HTTPException(status_code=409, detail="Vídeo já cadastrado neste projeto.")

    # 4. Se passou pelo escudo, cria o Vídeo
    novo_video = Video(
        project_id=project.id,
        original_filename=video_in.original_filename,
        location_name=video_in.location_name,
        file_path=video_in.file_path,
        status=VideoStatus.staged
    )
    
    db.add(novo_video)
    db.commit()
    db.refresh(novo_video)
    
    return novo_video
# 3. ROTA DELETE (Remove UM vídeo específico)
@app.delete("/videos/staged/{video_id}", status_code=204)
def delete_staged_video(video_id: int, db: Session = Depends(get_db)):
    """Remove um vídeo específico da fila de Staging."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    
    db.delete(video)
    db.commit()
    return

# 4. ROTA DELETE (Limpa a fila inteira)
@app.delete("/videos/staged", status_code=204)
def clear_staged_queue(db: Session = Depends(get_db)):
    """Remove TODOS os vídeos que estão com status 'staged' de uma vez."""
    # O .delete() direto no banco é muito mais rápido do que apagar um por um
    db.query(Video).filter(Video.status == "staged").delete()
    db.commit()
    return

# ==========================================
# ROTAS DE INTERFACE WEB (FRONT-END)
# ==========================================
@app.get("/admin/staging", response_class=HTMLResponse)
def render_admin_dashboard(request: Request):
    """Renderiza a página HTML do painel do Administrador."""
    # Correção: O FastAPI agora exige o parâmetro 'request' diretamente 
    # ou usando o nome 'context'
    return templates.TemplateResponse(
        request=request, 
        name="staging.html"
    )

if __name__ == "__main__":
    import uvicorn
    # Roda o servidor na porta 8000
    print("Iniciando o servidor ContaVias 2.0...")
    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True)