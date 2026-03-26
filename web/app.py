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

from models import init_db, Client, Project, Video, VideoStatus, VideoSlice, Zone
from web import schemas
from database import get_db

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

@app.post("/videos/{video_id}/slices/auto", response_model=List[schemas.VideoSliceResponse])
def create_auto_slices(video_id: int, slice_in: schemas.AutoSliceCreate, db: Session = Depends(get_db)):
    """Recebe um período (ex: 07:00 às 10:00) e fatia em blocos de 1 hora."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    
    # Converte os textos "07:00" para formato de Hora do Python
    formato = "%H:%M"
    t_start = datetime.strptime(slice_in.start_time, formato)
    t_end = datetime.strptime(slice_in.end_time, formato)

    slices_gerados = []
    tempo_atual = t_start

    # Loop que pula de 1 em 1 hora até chegar no fim
    while tempo_atual < t_end:
        proximo_tempo = tempo_atual + timedelta(hours=1)
        
        # Se o final do bloco passar do horário de término, a gente apara a aresta
        if proximo_tempo > t_end:
            proximo_tempo = t_end

        novo_slice = VideoSlice(
            video_id=video_id,
            start_time=tempo_atual.strftime(formato),
            end_time=proximo_tempo.strftime(formato),
            status="pending"
        )
        db.add(novo_slice)
        slices_gerados.append(novo_slice)
        
        tempo_atual = proximo_tempo

    db.commit()
    
    # Atualiza os IDs recém-criados
    for s in slices_gerados:
        db.refresh(s)

    return slices_gerados

@app.post("/videos/{video_id}/zones/bulk", response_model=List[schemas.ZoneResponse])
def create_video_zones_bulk(video_id: int, zones_in: List[schemas.ZoneCreate], db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    
    # MÁGICA: Apaga todas as zonas antigas deste vídeo antes de salvar a nova máscara!
    db.query(Zone).filter(Zone.video_id == video_id).delete()
    
    novas_zonas = []
    for zone_in in zones_in:
        nova_zone = Zone(
            video_id=video_id,
            name=zone_in.name,
            geometry_data = json.dumps(zone_in.geometry) 
        )
        db.add(nova_zone)
        novas_zonas.append(nova_zone)
    
    video.status = VideoStatus.configured
    db.commit()
    
    for nz in novas_zonas:
        db.refresh(nz)
        
    return novas_zonas

@app.patch("/videos/{video_id}/approve")
def approve_video_for_ai(video_id: int, db: Session = Depends(get_db)):
    """Muda o status do vídeo para 'approved' (Pronto para IA)."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    
    video.status = VideoStatus.approved
    db.commit()
    return {"message": "Vídeo liberado para processamento da IA!"}

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
    """Retorna vídeos e escaneia o disco para achar as URLs dos frames."""
    
    videos = db.query(Video).filter(
        Video.status.in_([
            VideoStatus.staged, 
            VideoStatus.ready, 
            VideoStatus.configured,
            VideoStatus.approved
        ])
    ).all()
    
    lista_videos = []
    
    # Caminho base físico onde os frames estão guardados
    base_frames_dir = os.path.join("web", "static", "frames")

    for v in videos:
        frame_urls = []
        
        # Só tentamos buscar frames se o vídeo já estiver baixado (ready ou configured)
        if v.status != VideoStatus.staged and v.project and v.project.client:
            # Recriamos o caminho da pasta física que o robô criou
            safe_client = limpar_nome_pasta_api(v.project.client.name)
            safe_project = limpar_nome_pasta_api(v.project.name)
            
            pasta_fisica_frames = os.path.join(
                base_frames_dir, safe_client, safe_project, f"id_{v.id}"
            )
            
            # Verificamos se a pasta existe fisicamente
            if os.path.exists(pasta_fisica_frames):
                # Lemos a lista de arquivos .jpg dentro dela
                arquivos = os.listdir(pasta_fisica_frames)
                frames_jpg = sorted([f for f in arquivos if f.endswith(".jpg")])
                
                # Montamos a URL pública que o navegador vai usar
                for f in frames_jpg:
                    url = f"/static/frames/{safe_client}/{safe_project}/id_{v.id}/{f}"
                    frame_urls.append(url)

        lista_videos.append({
            "id": v.id,
            "original_filename": v.original_filename,
            "status": v.status,
            "frame_urls": frame_urls,
            
            # A MÁGICA QUE FALTAVA AQUI 👇
            "zones": [{"name": z.name, "geometry": z.geometry} for z in v.zones],
            
            "project": {
                "name": v.project.name if v.project else "Sem Projeto",
                "client": {
                    "name": v.project.client.name if v.project and v.project.client else "Sem Cliente"
                }
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

if __name__ == "__main__":
    import uvicorn
    # Roda o servidor na porta 8000
    print("Iniciando o servidor ContaVias 2.0...")
    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True)