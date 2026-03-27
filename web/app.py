import os
import sys
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload

from fastapi import FastAPI, Depends, HTTPException, Request # <-- Adicione o Request aqui
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates 
from fastapi.responses import HTMLResponse

from datetime import datetime, timedelta
from typing import List

# Garante que o Python ache a pasta 'web' corretamente
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import init_db, Client, Project, Video, VideoStatus, VideoSlice, Zone, User, SliceStatus, Movement
from web import schemas
from database import get_db
from pydantic import BaseModel

import json

# Inicializa o banco de dados e cria a "fábrica" de sessões
SessionLocal = init_db()

def limpar_nome_pasta_api(nome):
    """Remove caracteres especiais para bater com as pastas criadas pelo robô."""
    import re
    return re.sub(r'[\\/*?:"<>|]', "", nome).strip()

app = FastAPI(
    title="ContaVias Server 2.0",
    description="API para gestão de inferência de vídeos e alocação de freelancers (Padrão DNIT)",
    version="2.0.0"
)

# Pega o caminho absoluto da pasta web
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Garante que a pasta static/frames existe fisicamente para o FastAPI não dar erro ao iniciar
os.makedirs(os.path.join(STATIC_DIR, "frames"), exist_ok=True)

# A MÁGICA: Abre a porta do cofre para o navegador acessar as imagens
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Configuração de CORS (Permite que o frontend se comunique com esta API)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Em produção, mudaremos para o domínio exato
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# NOVAS ROTAS DO ÉPICO 2: CONFIGURAÇÃO
# ==========================================

@app.post("/videos/{video_id}/slices/auto")
def create_auto_slices(video_id: int, slice_in: dict, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == video_id).first()
    
    def time_to_sec(t_str):
        h, m = map(int, t_str.split(':'))
        return h * 3600 + m * 60
        
    def sec_to_time(sec):
        h = (sec // 3600) % 24
        m = (sec % 3600) // 60
        return f"{h:02d}:{m:02d}"

    # O novo campo que virá do Staging
    base_sec = time_to_sec(slice_in.get("base_time", "00:00")) 
    
    start_sec = time_to_sec(slice_in.get("start_time", "00:00"))
    end_sec = time_to_sec(slice_in.get("end_time", "01:00"))
    
    db.query(VideoSlice).filter(VideoSlice.video_id == video_id).delete()
    
    slices = []
    current_start = start_sec
    NOMINAL_HOUR = 3600
    TOLERANCE = 180
    
    while current_start < end_sec:
        time_left = end_sec - current_start
        if time_left <= NOMINAL_HOUR + TOLERANCE:
            if time_left >= NOMINAL_HOUR - TOLERANCE:
                abs_start = base_sec + current_start
                abs_end = base_sec + end_sec
                label = f"{sec_to_time(abs_start)} - {sec_to_time(abs_end)}"
                slices.append(VideoSlice(video_id=video_id, name=label, start_time=current_start, end_time=end_sec))
            break
        else:
            abs_start = base_sec + current_start
            abs_end = base_sec + current_start + NOMINAL_HOUR
            label = f"{sec_to_time(abs_start)} - {sec_to_time(abs_end)}"
            slices.append(VideoSlice(video_id=video_id, name=label, start_time=current_start, end_time=current_start + NOMINAL_HOUR))
            current_start += NOMINAL_HOUR

    for s in slices:
        db.add(s)
    db.commit()
    return {"message": f"{len(slices)} fatias criadas com sucesso."}

@app.post("/projects/{project_id}/config")
def save_project_config(project_id: int, payload: schemas.ProjectConfigCreate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    
    # 1. Limpa as zonas e movimentos antigos deste projeto
    db.query(Zone).filter(Zone.project_id == project_id).delete()
    db.query(Movement).filter(Movement.project_id == project_id).delete()
    
    # 2. Salva as novas Zonas
    for zone_in in payload.zones:
        nova_zone = Zone(project_id=project_id, name=zone_in.name, geometry_data=json.dumps(zone_in.geometry))
        db.add(nova_zone)
        
    # 3. Salva os novos Movimentos
    for mov_name in payload.movements:
        novo_mov = Movement(project_id=project_id, name=mov_name)
        db.add(novo_mov)
    
    # Atualiza status dos vídeos
    videos_prontos = db.query(Video).filter(Video.project_id == project_id, Video.status == VideoStatus.ready).all()
    for v in videos_prontos:
        v.status = VideoStatus.configured

    db.commit()
    return {"message": "Máscara e Matriz OD salvas com sucesso!"}

@app.patch("/projects/{project_id}/approve")
def approve_project_for_ai(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    
    if not project.movements:
        raise HTTPException(status_code=400, detail="Desenhe as zonas e salve os Movimentos antes de aprovar!")
        
    videos = db.query(Video).filter(Video.project_id == project_id, Video.status == VideoStatus.configured).all()
    
    from models import MovementTask # Importe a nova tabela
    
    for v in videos:
        slices_to_process = v.slices
        # Se não tiver fatias, cria a fatia do Vídeo Completo
        if not slices_to_process:
            fatia = VideoSlice(video_id=v.id, name="Vídeo Completo", start_time=0, end_time=0, nominal_duration=0)
            db.add(fatia)
            db.flush() # Força o banco a gerar o ID da fatia imediatamente
            slices_to_process = [fatia]
            
        # MÁGICA: Para cada fatia, gera uma Tarefa para cada Movimento salvo!
        for sl in slices_to_process:
            for mov in project.movements:
                nova_tarefa = MovementTask(slice_id=sl.id, movement_id=mov.id)
                db.add(nova_tarefa)
                
        v.status = VideoStatus.approved
    db.commit()
    return {"message": f"Vídeos liberados e Matriz de Tarefas gerada!"}

@app.patch("/videos/{video_id}/ready")
def set_video_ready(video_id: int, db: Session = Depends(get_db)):
    """O robô chama esta rota quando termina o download e o OpenCV."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado")
    
    video.status = VideoStatus.ready
    db.commit()
    return {"message": f"Vídeo {video_id} está pronto para configuração"}

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
    videos = db.query(Video).filter(
        Video.status.in_([VideoStatus.staged, VideoStatus.ready, VideoStatus.configured])
    ).all()
    
    # MÁGICA DE REPLICAÇÃO: Se o projeto já tem máscara, o vídeo fica configurado automaticamente!
    for v in videos:
        if v.status == VideoStatus.ready and v.project and v.project.zones:
            v.status = VideoStatus.configured
            db.commit()

    import os
    lista_videos = []
    base_frames_dir = os.path.join("web", "static", "frames")

    for v in videos:
        frame_urls = []
        if v.status != VideoStatus.staged and v.project and v.project.client:
            safe_client = limpar_nome_pasta_api(v.project.client.name)
            safe_project = limpar_nome_pasta_api(v.project.name)
            pasta_fisica_frames = os.path.join(base_frames_dir, safe_client, safe_project, f"id_{v.id}")
            if os.path.exists(pasta_fisica_frames):
                arquivos = os.listdir(pasta_fisica_frames)
                frames_jpg = sorted([f for f in arquivos if f.endswith(".jpg")])
                for f in frames_jpg:
                    frame_urls.append(f"/static/frames/{safe_client}/{safe_project}/id_{v.id}/{f}")

        lista_videos.append({
            "id": v.id,
            "original_filename": v.original_filename,
            "status": v.status,
            "frame_urls": frame_urls,
            "zones": [{"name": z.name, "geometry": z.geometry} for z in v.project.zones] if v.project else [],
            
            "project": {
                "id": v.project.id,
                "name": v.project.name if v.project else "Sem Projeto",
                "client": {"name": v.project.client.name if v.project and v.project.client else "Sem Cliente"},
                
                # A LINHA MÁGICA QUE FALTAVA PARA CARREGAR OS TOGGLES:
                "movements": [m.name for m in v.project.movements] if v.project else []
                
            } if v.project else None
        })
    return {"videos": lista_videos}

# 2. ROTA POST (Usada pelo Robô do Drive para injetar vídeos novos)
@app.post("/videos/staged", response_model=schemas.VideoResponse, status_code=201)
def create_staged_video(video_in: schemas.VideoCreate, db: Session = Depends(get_db)):
    """Recebe o vídeo do robô, cria Cliente/Projeto se não existirem e salva o vídeo."""
    
    # 1. Procura o Cliente pelo nome (se não existir, cria)
    cliente = db.query(Client).filter(Client.name == video_in.client_name).first()
    if not cliente:
        cliente = Client(name=video_in.client_name)
        db.add(cliente)
        db.commit()
        db.refresh(cliente)

    # 2. Procura o Projeto pelo nome (amarrado ao Cliente). Se não existir, cria.
    projeto = db.query(Project).filter(
        Project.name == video_in.project_name, 
        Project.client_id == cliente.id
    ).first()
    if not projeto:
        projeto = Project(name=video_in.project_name, client_id=cliente.id)
        db.add(projeto)
        db.commit()
        db.refresh(projeto)

    # 3. Escudo Anti-Duplicidade (Garante que o vídeo não é repetido no projeto)
    video_existente = db.query(Video).filter(
        Video.original_filename == video_in.original_filename,
        Video.project_id == projeto.id
    ).first()
    if video_existente:
        raise HTTPException(status_code=409, detail="Vídeo já existe neste projeto")

    # 4. Salva o Vídeo amarrado ao Projeto correto!
    novo_video = Video(
        project_id=projeto.id,
        original_filename=video_in.original_filename,
        location_name=video_in.location_name,
        file_path=video_in.file_path,
        status=VideoStatus.staged
    )
    db.add(novo_video)
    db.commit()
    db.refresh(novo_video)
    
    return novo_video

@app.delete("/videos/staged/{video_id}")
def delete_staged_video(video_id: int, db: Session = Depends(get_db)):
    """Remove um vídeo específico da fila."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado")
    
    db.delete(video)
    db.commit()
    return {"message": "Vídeo removido com sucesso"}

@app.delete("/videos/staged")
def clear_staged_videos(db: Session = Depends(get_db)):
    """Limpa todos os vídeos que ainda não foram para a IA."""
    videos = db.query(Video).filter(
        Video.status.in_([VideoStatus.staged, VideoStatus.ready, VideoStatus.configured])
    ).all()
    
    for v in videos:
        db.delete(v)
        
    db.commit()
    return {"message": f"{len(videos)} vídeos removidos da fila."}

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

# ==========================================
# ROTAS DO ÉPICO 3: GESTÃO E ALOCAÇÃO
# ==========================================

# 1. Rota para carregar o HTML da tela de Alocação
@app.get("/admin/allocation")
def allocation_page(request: Request):
    # Passando os parâmetros com seus nomes oficiais para não haver confusão
    return templates.TemplateResponse(request=request, name="allocation.html", context={"request": request})

# 2. Rota para criar um novo Freelancer
@app.post("/users", response_model=schemas.UserResponse)
def create_user(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    # Simples verificação se o email já existe
    if db.query(User).filter(User.email == user_in.email).first():
        raise HTTPException(status_code=400, detail="Email já cadastrado.")
    
    novo_user = User(name=user_in.name, email=user_in.email, role="freelancer")
    db.add(novo_user)
    db.commit()
    db.refresh(novo_user)
    return novo_user

# 3. Rota que alimenta a tela de alocação (Traz Freelas + Vídeos Aprovados)
@app.get("/allocation/data")
def get_allocation_data(db: Session = Depends(get_db)):
    freelancers = db.query(User).filter(User.role == "freelancer").all()
    videos = db.query(Video).filter(Video.status.in_([VideoStatus.approved, VideoStatus.processing])).all()
    freelas_data = [{"id": f.id, "name": f.name} for f in freelancers]
    
    videos_data = []
    for v in videos:
        slices_data = []
        for s in v.slices:
            # Lendo as tarefas dentro da fatia
            tasks_data = []
            for t in s.tasks:
                tasks_data.append({
                    "id": t.id,
                    "movement_name": t.movement.name,
                    "status": t.status,
                    "freelancer_name": t.freelancer.name if t.freelancer else None
                })
                
            slices_data.append({
                "id": s.id, "name": s.name, "start_time": s.start_time, "end_time": s.end_time,
                "tasks": tasks_data # Envia as tarefas em vez do status único
            })
        videos_data.append({"id": v.id, "project_name": v.project.name if v.project else "Sem Projeto", "filename": v.original_filename, "status": v.status, "slices": slices_data})
    return {"freelancers": freelas_data, "videos": videos_data}

# 4. Rota para o Admin atribuir uma fatia a um Freela
@app.patch("/slices/{slice_id}/assign")
def assign_slice(slice_id: int, payload: dict, db: Session = Depends(get_db)):
    user_id = payload.get("user_id")
    v_slice = db.query(VideoSlice).filter(VideoSlice.id == slice_id).first()
    
    if not v_slice:
        raise HTTPException(status_code=404, detail="Fatia não encontrada.")
        
    v_slice.assigned_to = user_id
    v_slice.status = SliceStatus.assigned
    
    # Se o vídeo estava só 'aprovado', agora ele muda para 'processando' pois o trabalho começou!
    if v_slice.video.status == VideoStatus.approved:
        v_slice.video.status = VideoStatus.processing
        
    db.commit()
    return {"message": "Fatia atribuída com sucesso!"}

class AssignTasksPayload(BaseModel):
    task_ids: List[int]
    user_id: int

@app.patch("/tasks/assign_bulk")
def assign_tasks_bulk(payload: AssignTasksPayload, db: Session = Depends(get_db)):
    from models import MovementTask
    tasks = db.query(MovementTask).filter(MovementTask.id.in_(payload.task_ids)).all()
    for t in tasks:
        t.assigned_to = payload.user_id
        t.status = SliceStatus.assigned
        if t.video_slice.video.status == VideoStatus.approved:
            t.video_slice.video.status = VideoStatus.processing
    db.commit()
    return {"message": f"{len(tasks)} tarefas atribuídas com sucesso!"}

if __name__ == "__main__":
    import uvicorn
    # Roda o servidor na porta 8000
    print("Iniciando o servidor ContaVias 2.0...")
    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True)