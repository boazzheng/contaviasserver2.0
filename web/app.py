import os
import sys
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import Optional, List # Adicione isso no topo do arquivo se não tiver

from fastapi import FastAPI, Depends, HTTPException, Request # <-- Adicione o Request aqui
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates 
from fastapi.responses import HTMLResponse

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
    from models import Project, Zone, Movement, Video, VideoStatus, MovementTask, CountRecord, VideoSlice
    import json
    
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    
    # 1. MAPEAMENTO DAS NOVAS ZONAS
    # Primeiro guardamos os nomes das zonas que estão a entrar agora
    nomes_zonas_vivas = {z.name.strip() for z in payload.zones}

    # 2. HIGIENIZAÇÃO AUTOMÁTICA DOS MOVIMENTOS
    # Filtramos a lista de movimentos para garantir que SÓ fiquem os que usam zonas existentes
    movimentos_validados = []
    for mov_str in payload.movements:
        partes = mov_str.split(" ➔ ") if " ➔ " in mov_str else mov_str.split(" -> ")
        if len(partes) == 2:
            origem, destino = partes[0].strip(), partes[1].strip()
            # SÓ adicionamos o movimento se AMBAS as zonas existirem na nova lista
            if origem in nomes_zonas_vivas and destino in nomes_zonas_vivas:
                movimentos_validados.append(mov_str)
            else:
                print(f"🧹 Higienizador: Removendo movimento órfão '{mov_str}'")

    # 3. RECRIA AS ZONAS (Físicas no Banco)
    db.query(Zone).filter(Zone.project_id == project_id).delete(synchronize_session=False)
    for zone_in in payload.zones:
        nova_zone = Zone(project_id=project_id, name=zone_in.name, geometry_data=json.dumps(zone_in.geometry))
        db.add(nova_zone)
        
    # 4. SINCRONIZAÇÃO DOS MOVIMENTOS (Baseada na lista validada)
    movimentos_atuais_db = db.query(Movement).filter(Movement.project_id == project_id).all()
    mapa_db = {m.name: m for m in movimentos_atuais_db}
    set_novos = set(movimentos_validados)
    
    # A. Deletar o que saiu (incluindo os órfãos que o higienizador barrou)
    for nome_db, mov_obj in mapa_db.items():
        if nome_db not in set_novos:
            # Purgar tarefas e contagens vinculadas a este movimento extinto
            tarefas = db.query(MovementTask).filter(MovementTask.movement_id == mov_obj.id).all()
            ids_t = [t.id for t in tarefas]
            if ids_t:
                db.query(CountRecord).filter(CountRecord.task_id.in_(ids_t)).delete(synchronize_session=False)
                db.query(MovementTask).filter(MovementTask.id.in_(ids_t)).delete(synchronize_session=False)
            db.delete(mov_obj)
            
    # B. Adicionar o que é novo
    novos_mov_objs = []
    for nome_n in set_novos:
        if nome_n not in mapa_db:
            nm = Movement(project_id=project_id, name=nome_n)
            db.add(nm)
            novos_mov_objs.append(nm)
            
    db.flush() 
    
    # 5. PROPAGAÇÃO PARA VÍDEOS JÁ APROVADOS
    if novos_mov_objs:
        videos_ativos = db.query(Video).filter(
            Video.project_id == project_id,
            Video.status.in_([VideoStatus.approved, "approved", "completed"])
        ).all()
        
        for v in videos_ativos:
            for fatia in v.slices:
                for nm in novos_mov_objs:
                    # Cria a tarefa nova para o freela contar o novo movimento
                    db.add(MovementTask(slice_id=fatia.id, movement_id=nm.id, status="pending"))

    # 6. Atualiza status de vídeos em espera
    db.query(Video).filter(
        Video.project_id == project_id, 
        Video.status == VideoStatus.ready
    ).update({"status": VideoStatus.configured}, synchronize_session=False)

    db.commit()
    return {"message": "Configuração sincronizada e movimentos órfãos removidos!"}

@app.patch("/projects/{project_id}/approve")
def approve_project_for_ai(project_id: int, db: Session = Depends(get_db)):
    try:
        from models import Project, Video, VideoSlice, MovementTask
        # Importe os seus Enums de status se necessário (ajuste conforme o seu código)
        from models import VideoStatus, SliceStatus 
        
        project = db.query(Project).filter(Project.id == project_id).first()
        
        if not project or not project.movements:
            raise HTTPException(status_code=400, detail="Desenhe as zonas e salve os Movimentos antes de aprovar!")
            
        videos = db.query(Video).filter(Video.project_id == project_id, Video.status == VideoStatus.configured).all()
        
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
                    # 🔴 ADICIONADO: Forçamos o status=SliceStatus.pending para evitar erros de valor nulo no SQLite
                    nova_tarefa = MovementTask(
                        slice_id=sl.id, 
                        movement_id=mov.id,
                        status=SliceStatus.pending 
                    )
                    db.add(nova_tarefa)
                    
            v.status = VideoStatus.approved
            
        db.commit()
        return {"message": "Vídeos liberados e Matriz de Tarefas gerada!"}
        
    except HTTPException:
        # Repassa os erros 400 (ex: "Desenhe as zonas...") diretamente para a interface
        raise
    except Exception as e:
        # Se bater na parede, cancela tudo, imprime o erro gigante no terminal e avisa a tela!
        db.rollback()
        print(f"🚨 ERRO CRÍTICO AO LIBERAR PROJETO {project_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erro no banco de dados: {str(e)}")
    
@app.patch("/videos/{video_id}/ready")
def mark_video_ready(video_id: int, db: Session = Depends(get_db)):
    from models import Video, VideoStatus
    
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado")
        
    # 🔴 O ESCUDO ANTI-FANTASMA: Se já passou do estágio 'ready', ignora a requisição!
    status_atual = str(video.status).replace("VideoStatus.", "")
    if status_atual in ["configured", "approved", "completed"]:
        return {"message": "O vídeo já avançou no fluxo. Status não alterado."}
        
    video.status = VideoStatus.ready
    db.commit()
    return {"message": "Vídeo marcado como pronto para configuração."}

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
    # Pega a pasta física real onde este código está rodando e junta com static/frames
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    base_frames_dir = os.path.join(diretorio_atual, "static", "frames")

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
                    print(f"   ✅ Frame encontrado para vídeo {v.id}: {f} do cliente '{safe_client}' e projeto '{safe_project}'", flush=True)
            else:
                print(f"❌ Pasta não encontrada: {pasta_fisica_frames}", flush=True)

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
        # Em vez de apenas raise HTTPException(409), retornamos o vídeo com o status 409
        # Isso permite que o robô receba o ID do vídeo
        from fastapi.responses import JSONResponse
        from fastapi.encoders import jsonable_encoder
        
        conteudo = jsonable_encoder(video_existente)
        return JSONResponse(status_code=409, content=conteudo)

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
    from models import Video, User, VideoStatus, MovementTask, WorkPackage
    
    freelas = db.query(User).filter(User.role == "freelancer").all()
    
    videos = db.query(Video).filter(
        Video.status.in_([VideoStatus.approved, VideoStatus.configured, "approved"])
    ).all()
    
    video_list = []
    for v in videos:
        slices_data = []
        for sl in v.slices:
            tasks_data = []
            for t in sl.tasks:
                # 🔴 BUSCA SEGURA E BLINDADA
                freela_name = None
                if t.assigned_to:
                    user_obj = db.query(User).filter(User.id == t.assigned_to).first()
                    if user_obj:
                        freela_name = user_obj.name
                
                package_name = None
                if getattr(t, 'work_package_id', None):
                    pacote = db.query(WorkPackage).filter(WorkPackage.id == t.work_package_id).first()
                    if pacote:
                        package_name = pacote.name
                
                # Tratamento seguro do status
                status_valor = t.status.value if hasattr(t.status, 'value') else str(t.status).replace("SliceStatus.", "")
                
                tasks_data.append({
                    "id": t.id,
                    "movement_name": t.movement.name if t.movement else "Movimento",
                    "status": status_valor,
                    "freelancer_name": freela_name,
                    "package_name": package_name
                })
            
            slices_data.append({
                "id": sl.id,
                "name": sl.name,
                "start_time": sl.start_time,
                "end_time": sl.end_time,
                "tasks": tasks_data,
                "videoId": v.id,
                "filename": v.original_filename
            })
            
        video_list.append({
            "id": v.id,
            "filename": v.original_filename,
            "project_name": v.project.name if v.project else "Sem Projeto",
            "slices": slices_data
        })
        
    return {
        "freelancers": [{"id": f.id, "name": f.name} for f in freelas],
        "videos": video_list
    }

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

@app.patch("/videos/{video_id}/revert") # Atenção: verifique se a sua URL é exatamente esta
def revert_video_to_staging(video_id: int, db: Session = Depends(get_db)):
    from models import Video, VideoSlice, MovementTask, CountRecord
    
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado")
        
    # Limpar todas as Fatias, Tarefas e Contagens antigas deste vídeo!
    for fatia in video.slices:
        tarefas_ids = [t.id for t in fatia.tasks]
        
        # 1. Apaga os registros (cliques) perdidos nessas tarefas
        if tarefas_ids:
            db.query(CountRecord).filter(CountRecord.task_id.in_(tarefas_ids)).delete(synchronize_session=False)
        
        # 2. Apaga as tarefas antigas
        db.query(MovementTask).filter(MovementTask.slice_id == fatia.id).delete(synchronize_session=False)
        
    # 3. Apaga as Fatias (Slices) antigas
    db.query(VideoSlice).filter(VideoSlice.video_id == video.id).delete(synchronize_session=False)
    
    # 4. Devolve o vídeo para a estaca zero
    # Use "staged" ou "ready" dependendo de como o seu escaneador funciona
    video.status = "ready" 
    
    db.commit()
    return {"message": "Vídeo revertido e limpo com sucesso!"}

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

from pydantic import BaseModel
from typing import List

class CreateWorkPackageRequest(BaseModel):
    name: str
    freelancer_id: int
    task_ids: List[int]

@app.post("/api/admin/work-packages")
def create_work_package(payload: CreateWorkPackageRequest, db: Session = Depends(get_db)):
    try:
        from models import WorkPackage, MovementTask, VideoSlice, Video
        
        # 1. Descobre a qual Projeto de verdade essas tarefas pertencem
        primeira_tarefa = db.query(MovementTask).filter(MovementTask.id == payload.task_ids[0]).first()
        fatia = db.query(VideoSlice).filter(VideoSlice.id == primeira_tarefa.slice_id).first() if primeira_tarefa else None
        video = db.query(Video).filter(Video.id == fatia.video_id).first() if fatia else None
        projeto_id = video.project_id if video else None

        if not projeto_id:
            raise HTTPException(status_code=400, detail="Tarefas órfãs sem projeto.")

        # 2. SMART MERGE: Verifica se já existe um Lote ABERTO deste freela para este projeto
        pacote_existente = db.query(WorkPackage).filter(
            WorkPackage.freelancer_id == payload.freelancer_id,
            WorkPackage.project_id == projeto_id,
            WorkPackage.status != "completed"  # Só pega pacotes em andamento
        ).first()

        pacote_ativo_id = None

        if pacote_existente:
            # Se já tem, vamos apenas aproveitar o "envelope" existente!
            pacote_ativo_id = pacote_existente.id
            
            # (Opcional) Se o admin digitou um nome novo, atualizamos o nome do lote
            if payload.name and payload.name.strip() != "":
                pacote_existente.name = payload.name
            
            db.flush()
        else:
            # 3. Se não tem, cria um Lote novinho em folha
            # Se o admin não digitou nome, o sistema cria um nome automático limpo
            nome_pacote = payload.name if payload.name.strip() != "" else f"Lote de Trabalho - Projeto #{projeto_id}"
            
            novo_pacote = WorkPackage(
                name=nome_pacote,
                freelancer_id=payload.freelancer_id,
                project_id=projeto_id,
                status="pending"
            )
            db.add(novo_pacote)
            db.flush()
            pacote_ativo_id = novo_pacote.id
        
        # 4. Atualiza todas as tarefas selecionadas para entrarem no Lote Ativo (novo ou existente)
        db.query(MovementTask).filter(MovementTask.id.in_(payload.task_ids)).update({
            "work_package_id": pacote_ativo_id,
            "assigned_to": payload.freelancer_id,
            "status": "pending" # Reseta caso seja uma realocação
        }, synchronize_session=False)
        
        db.commit()
        
        mensagem = "Tarefas adicionadas ao lote existente!" if pacote_existente else "Novo Lote criado e alocado!"
        return {"message": mensagem, "package_id": pacote_ativo_id}
        
    except Exception as e:
        db.rollback()
        print(f"🚨 ERRO AO ALOCAR LOTE: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")
        
# ==========================================
# ROTAS DO ÉPICO 4: WORKSPACE DO FREELANCER
# ==========================================

@app.get("/freelancer/workspace", response_class=HTMLResponse)
def workspace_page(request: Request):
    """Renderiza a casca do Dashboard do Freelancer."""
    return templates.TemplateResponse(request=request, name="workspace.html")

@app.get("/api/freelancer/workspace/{user_id}")
def get_workspace_data(user_id: int, db: Session = Depends(get_db)):
    try:
        from models import User, WorkPackage, MovementTask, SliceStatus, VideoSlice, Video
        
        freela = db.query(User).filter(User.id == user_id).first()
        if not freela:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        
        pacotes = db.query(WorkPackage).filter(
            WorkPackage.freelancer_id == user_id,
            WorkPackage.status != "completed"
        ).all()
        
        packages_data = []
        total_tasks_global = 0
        
        for p in pacotes:
            tarefas = db.query(MovementTask).filter(MovementTask.work_package_id == p.id).all()
            total_tasks = len(tarefas)
            completed_tasks = sum(1 for t in tarefas if t.status == SliceStatus.completed)
            total_tasks_global += (total_tasks - completed_tasks)
            
            agrupamento_videos = {}
            for t in tarefas:
                if t.status == SliceStatus.completed:
                    continue 
                
                # Busca segura de relações
                fatia = db.query(VideoSlice).filter(VideoSlice.id == t.slice_id).first()
                video = db.query(Video).filter(Video.id == fatia.video_id).first() if fatia else None
                
                if not fatia or not video:
                    continue
                
                v_id = video.id
                if v_id not in agrupamento_videos:
                    agrupamento_videos[v_id] = {
                        "video_id": v_id,
                        "filename": video.original_filename,
                        "project_name": f"Projeto #{video.project_id}",
                        "slices": {}
                    }
                
                s_id = fatia.id
                if s_id not in agrupamento_videos[v_id]["slices"]:
                    agrupamento_videos[v_id]["slices"][s_id] = {
                        "slice_id": s_id,
                        "name": fatia.name,
                        "tasks": []
                    }
                
                movimento_nome = t.movement.name if hasattr(t, 'movement') and t.movement else "Movimento"
                agrupamento_videos[v_id]["slices"][s_id]["tasks"].append({
                    "id": t.id,
                    "movement_name": movimento_nome
                })
            
            for v in agrupamento_videos.values():
                v["slices"] = list(v["slices"].values())
                
            packages_data.append({
                "package_id": p.id,
                "package_name": p.name,
                "project_name": f"Projeto #{p.project_id}",
                "progress": f"{completed_tasks}/{total_tasks} Movimentos Concluídos",
                "videos": list(agrupamento_videos.values())
            })
        
        return {
            "freelancer_name": freela.name,
            "total_tasks": total_tasks_global,
            "total_packages": len(packages_data),
            "packages": packages_data
        }
    except Exception as e:
        print(f"🚨 ERRO NO WORKSPACE: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno no servidor")
    
# Rota para renderizar a tela do Reprodutor
@app.get("/freelancer/workspace/counter/{slice_id}", response_class=HTMLResponse)
def counter_page(request: Request, slice_id: int):
    return templates.TemplateResponse(request=request, name="counter.html", context={"slice_id": slice_id})

# 1. Definição do formato de dados que vamos receber
class RecordItem(BaseModel):
    vehicle_class: str
    video_time: float

class CompleteTaskRequest(BaseModel):
    records: List[RecordItem]

# 2. A rota exata que o frontend está a chamar
@app.post("/api/tasks/{task_id}/complete")
def complete_task(task_id: int, payload: CompleteTaskRequest, db: Session = Depends(get_db)):
    from models import MovementTask, SliceStatus, CountRecord, WorkPackage
    
    task = db.query(MovementTask).filter(MovementTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
        
    # Muda o status para concluído
    task.status = SliceStatus.completed

    # Limpa rascunhos antigos dessa tarefa
    db.query(CountRecord).filter(CountRecord.task_id == task_id).delete()

    # Grava os novos registros oficiais
    novos_registros = []
    for r in payload.records:
        novo = CountRecord(
            task_id=task_id,
            vehicle_class=r.vehicle_class,
            video_time=r.video_time
        )
        novos_registros.append(novo)
    
    db.add_all(novos_registros)
    db.commit()

    # 🔴 NOVO: VERIFICAÇÃO DE FECHAMENTO DO PACOTE
    if task.work_package_id:
        pacote_id = task.work_package_id
        # Busca TODAS as tarefas que pertencem a este mesmo pacote
        todas_tarefas_pacote = db.query(MovementTask).filter(MovementTask.work_package_id == pacote_id).all()
        
        # Verifica se TODAS estão concluídas
        todas_concluidas = all(t.status == SliceStatus.completed for t in todas_tarefas_pacote)
        
        if todas_concluidas:
            pacote = db.query(WorkPackage).filter(WorkPackage.id == pacote_id).first()
            if pacote:
                pacote.status = "completed"
                db.commit()
                print(f"🎉 PACOTE FECHADO: O Pacote {pacote.name} foi 100% concluído!")

    return {"message": "Tarefa concluída e salva com sucesso!"}

@app.get("/api/workspace/slice/{slice_id}/data")
def get_slice_counter_data(slice_id: int, user_id: int, review: str = "false", task_id: Optional[int] = None, db: Session = Depends(get_db)):
    from models import VideoSlice, MovementTask, CountRecord, SliceStatus
    import re
    
    fatia = db.query(VideoSlice).filter(VideoSlice.id == slice_id).first()
    if not fatia:
        raise HTTPException(status_code=404, detail="Fatia não encontrada")
        
    if review.lower() == "true":
        query = db.query(MovementTask).filter(
            MovementTask.slice_id == slice_id,
            MovementTask.assigned_to == user_id
        )
        if task_id:
            query = query.filter(MovementTask.id == task_id)
            
        tarefas = query.all()
    else:
        tarefas = db.query(MovementTask).filter(
            MovementTask.slice_id == slice_id,
            MovementTask.assigned_to == user_id,
            MovementTask.status != SliceStatus.completed
        ).all()
        
    tarefa_ids = [t.id for t in tarefas]
    registros_db = db.query(CountRecord).filter(CountRecord.task_id.in_(tarefa_ids)).all()
    
    registros_formatados = [{
        "task_id": r.task_id,
        "vehicle_class": r.vehicle_class,
        "video_time": r.video_time
    } for r in registros_db]

    def limpar_nome(nome):
        return re.sub(r'[\\/*?:"<>|]', "", nome).strip()
        
    cliente = fatia.video.project.client.name if fatia.video.project and fatia.video.project.client else "Cliente Padrão"
    projeto = fatia.video.project.name if fatia.video.project else "Projeto Padrão"
    url_video = f"/static/videos/{limpar_nome(cliente)}/{limpar_nome(projeto)}/{fatia.video.original_filename}"
    
    zonas_do_projeto = {}
    if fatia.video.project and hasattr(fatia.video.project, 'zones'):
        for z in fatia.video.project.zones:
            zonas_do_projeto[z.name.strip()] = z.geometry

    tasks_data = []
    for t in tarefas:
        task_info = {
            "id": t.id, 
            "movement_name": t.movement.name if t.movement else "Desconhecido",
            "origin_zone": None,
            "destination_zone": None
        }
        
        # A MÁGICA: Corta o nome "Origem ➔ Destino" para achar as zonas!
        if t.movement and t.movement.name:
            # Tenta separar pela seta que usamos no frontend
            partes = t.movement.name.split(" ➔ ")
            if len(partes) != 2: 
                partes = t.movement.name.split(" -> ") # Plano B caso a seta seja diferente
                
            if len(partes) == 2:
                nome_origem = partes[0].strip()
                nome_destino = partes[1].strip()
                
                # Procura as zonas cortadas dentro do dicionário do projeto
                if nome_origem in zonas_do_projeto:
                    task_info["origin_zone"] = {
                        "name": nome_origem,
                        "geometry": zonas_do_projeto[nome_origem]
                    }
                    
                if nome_destino in zonas_do_projeto:
                    task_info["destination_zone"] = {
                        "name": nome_destino,
                        "geometry": zonas_do_projeto[nome_destino]
                    }
                
        tasks_data.append(task_info)
    
    return {
        "video_url": url_video,
        "slice_name": fatia.name,
        "project_name": f"Projeto #{fatia.video.project_id}",
        "tasks": tasks_data, 
        "existing_records": registros_formatados
    }

# Rota para salvar a bateria de contagens (timestamps)
class CountRecordSchema(BaseModel):
    task_id: int
    vehicle_class: str
    video_time: float

class SaveCountsPayload(BaseModel):
    records: List[CountRecordSchema]

@app.post("/api/workspace/slice/{slice_id}/save")
def save_counts(slice_id: int, payload: SaveCountsPayload, db: Session = Depends(get_db)):
    from models import CountRecord, MovementTask, SliceStatus
    
    # 1. Insere todos os cliques no banco
    for record in payload.records:
        novo_registro = CountRecord(
            task_id=record.task_id,
            vehicle_class=record.vehicle_class,
            video_time=record.video_time
        )
        db.add(novo_registro)
        
    # 2. Marca as tarefas como concluídas
    task_ids = set([r.task_id for r in payload.records])
    for tid in task_ids:
        task = db.query(MovementTask).filter(MovementTask.id == tid).first()
        if task:
            task.status = SliceStatus.completed
            
    db.commit()
    return {"message": "Contagens salvas com sucesso!"}

@app.get("/api/workspace/{user_id}/history")
def get_user_history(user_id: int, db: Session = Depends(get_db)):
    try:
        # Adicionamos o VideoSlice aqui nos imports
        from models import MovementTask, SliceStatus, CountRecord, VideoSlice
        from sqlalchemy import func

        tarefas_concluidas = db.query(MovementTask).filter(
            MovementTask.assigned_to == user_id,
            MovementTask.status == SliceStatus.completed
        ).all()

        resultado = []
        for t in tarefas_concluidas:
            total_veiculos = db.query(func.count(CountRecord.id)).filter(CountRecord.task_id == t.id).scalar() or 0
            
            # 🔴 SOLUÇÃO BULLETPROOF: Buscamos a fatia diretamente pelo ID
            fatia = db.query(VideoSlice).filter(VideoSlice.id == t.slice_id).first()
            video = fatia.video if fatia else None
            projeto = video.project if video else None
            video_nome = video.original_filename if video else "Vídeo Desconhecido" # 👈 NOVO
            
            resultado.append({
                "task_id": t.id,
                "video_filename": video_nome,
                "project": f"Projeto #{projeto.id}" if projeto else "Avulso",
                "movement": t.movement.name if hasattr(t, 'movement') and t.movement else "Movimento",
                "slice_name": fatia.name if fatia else "Desconhecida",
                "total": total_veiculos,
                "slice_id": t.slice_id
            })
        
        return resultado[::-1]
    
    except Exception as e:
        print(f"🚨 ERRO NA ROTA DE HISTÓRICO: {str(e)}")
        # Imprime o erro completo no terminal para facilitar debugging futuro
        import traceback
        traceback.print_exc()
        return []
       
# ==========================================
# ROTAS CONTAGEM TOTAL DOS FREELANCER
# ==========================================

@app.get("/api/admin/reports/{project_id}")
def get_project_report(project_id: int, db: Session = Depends(get_db)):
    from models import Project, Video, VideoSlice, MovementTask, CountRecord, SliceStatus
    
    # 1. Busca o projeto e valida
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
        
    # 2. Coleta todos os dados em cascata
    # Buscamos todos os vídeos do projeto -> todas as fatias -> todas as tarefas concluídas
    videos = db.query(Video).filter(Video.project_id == project_id).all()
    video_ids = [v.id for v in videos]
    
    slices = db.query(VideoSlice).filter(VideoSlice.video_id.in_(video_ids)).all()
    slice_ids = [s.id for s in slices]
    
    # IMPORTANTE: Pegamos apenas o que os freelas já finalizaram
    tasks = db.query(MovementTask).filter(
        MovementTask.slice_id.in_(slice_ids),
        MovementTask.status == SliceStatus.completed
    ).all()
    
    task_ids = [t.id for t in tasks]
    records = db.query(CountRecord).filter(CountRecord.task_id.in_(task_ids)).all()
    
    # 3. Mapeamento para performance (evita milhares de consultas ao banco no loop)
    task_map = {t.id: t for t in tasks}
    video_map = {v.id: v for v in videos}
    slice_map = {s.id: s for s in slices}
    
    # 4. Agregação por Bloco de 15 minutos
    report_dict = {}
    
    for r in records:
        task = task_map.get(r.task_id)
        if not task: continue
        
        fatia = slice_map.get(task.slice_id)
        video = video_map.get(fatia.video_id)
        
        mov_name = task.movement.name if task.movement else "Movimento Indefinido"
        video_filename = video.original_filename
        
        # Cálculo do intervalo (ex: clique aos 18min vira bloco de 15-30)
        bloco_idx = int(r.video_time // 900)
        intervalo_txt = f"{str(bloco_idx * 15).zfill(2)}:00 - {str((bloco_idx + 1) * 15).zfill(2)}:00"
        
        # Chave única para agrupar (Mesmo vídeo + Mesmo Movimento + Mesmo Intervalo)
        chave = f"{video_filename}|{mov_name}|{intervalo_txt}"
        
        if chave not in report_dict:
            report_dict[chave] = {
                "video": video_filename,
                "movement": mov_name,
                "interval": intervalo_txt,
                "sort_key": bloco_idx, # Usado apenas para ordenar a lista depois
                "Carro": 0, "Moto": 0, "Ônibus": 0, "Caminhão": 0
            }
        
        # Soma o veículo à contagem
        classe = r.vehicle_class
        if classe in report_dict[chave]:
            report_dict[chave][classe] += 1
            
    # 5. Ordenação Final (Por Nome de Vídeo -> Movimento -> Horário)
    resultado_final = list(report_dict.values())
    resultado_final.sort(key=lambda x: (x['video'], x['movement'], x['sort_key']))
    
    return {
        "project_name": project.name,
        "client_name": project.client.name if project.client else "N/A",
        "data": resultado_final
    }

@app.get("/admin/reports", response_class=HTMLResponse)
def view_reports_page(request: Request):
    # O FastAPI mais recente exige que os parâmetros sejam nomeados assim:
    return templates.TemplateResponse(
        request=request, 
        name="reports.html"
    )

if __name__ == "__main__":
    import uvicorn
    # Roda o servidor na porta 8000
    print("Iniciando o servidor ContaVias 2.0...")
    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True)

    # uvicorn app:app --reload