import os
import json
import re
from typing import List, Dict
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.encoders import jsonable_encoder
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel

from database import get_db
from models import (Project, Zone, Movement, Video, VideoStatus, MovementTask, 
                    CountRecord, VideoSlice, SliceStatus, Client, User, WorkPackage, MovementTask)
from web import schemas
import pandas as pd
import io
from datetime import datetime

router = APIRouter()

# Configuração de Templates local para o Router
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

def limpar_nome_pasta_api(nome):
    return re.sub(r'[\\/*?:"<>|]', "", nome).strip()

# --- MODELOS INLINE ---
class AssignTasksPayload(BaseModel):
    task_ids: List[int]
    user_id: int

class CreateWorkPackageRequest(BaseModel):
    name: str
    freelancer_id: int
    task_ids: List[int]

# ==========================================
# GESTÃO DE VÍDEOS E STAGING
# ==========================================
@router.get("/admin/staging", response_class=HTMLResponse)
def render_admin_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="staging.html")

@router.get("/videos/staged")
def get_staged_videos(db: Session = Depends(get_db)):
    videos = db.query(Video).filter(
        Video.status.in_([
            VideoStatus.staged, 
            VideoStatus.ready, 
            VideoStatus.configured, 
            VideoStatus.processing,
            VideoStatus.approved,
        ])
    ).all()
    
    for v in videos:
        # Só atualiza para configured se estiver ready (não mexe nos processing)
        if v.status == VideoStatus.ready and v.project and v.project.zones:
            v.status = VideoStatus.configured
            db.commit()

    diretorio_atual = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base_frames_dir = os.path.join(diretorio_atual, "static", "frames")
    lista_videos = []

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
            "is_validation": v.is_validation,
            "frame_urls": frame_urls,
            "zones": [{"name": z.name, "geometry": z.geometry} for z in v.project.zones] if v.project else [],
            "project": {
                "id": v.project.id,
                "name": v.project.name if v.project else "Sem Projeto",
                "client": {"name": v.project.client.name if v.project and v.project.client else "Sem Cliente"},
                "movements": [m.name for m in v.project.movements] if v.project else []
            } if v.project else None
        })
    return {"videos": lista_videos}

@router.post("/videos/staged", response_model=schemas.VideoResponse, status_code=201)
def create_staged_video(video_in: schemas.VideoCreate, db: Session = Depends(get_db)):
    cliente = db.query(Client).filter(Client.name == video_in.client_name).first()
    if not cliente:
        cliente = Client(name=video_in.client_name)
        db.add(cliente)
        db.commit()
        db.refresh(cliente)

    projeto = db.query(Project).filter(Project.name == video_in.project_name, Project.client_id == cliente.id).first()
    if not projeto:
        projeto = Project(name=video_in.project_name, client_id=cliente.id)
        db.add(projeto)
        db.commit()
        db.refresh(projeto)

    video_existente = db.query(Video).filter(Video.original_filename == video_in.original_filename, Video.project_id == projeto.id).first()
    if video_existente:
        return JSONResponse(status_code=409, content=jsonable_encoder(video_existente))

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

@router.delete("/videos/staged/{video_id}")
def delete_staged_video(video_id: int, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado")
    db.delete(video)
    db.commit()
    return {"message": "Vídeo removido com sucesso"}

@router.delete("/videos/staged")
def clear_staged_videos(db: Session = Depends(get_db)):
    videos = db.query(Video).filter(Video.status.in_([VideoStatus.staged, VideoStatus.ready, VideoStatus.configured])).all()
    for v in videos:
        db.delete(v)
    db.commit()
    return {"message": f"{len(videos)} vídeos removidos da fila."}

@router.patch("/videos/{video_id}/ready")
def mark_video_ready(video_id: int, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado")
    status_atual = str(video.status).replace("VideoStatus.", "")
    if status_atual in ["configured", "approved", "completed"]:
        return {"message": "O vídeo já avançou no fluxo. Status não alterado."}
    video.status = VideoStatus.ready
    db.commit()
    return {"message": "Vídeo marcado como pronto."}


# ==========================================
# CONFIGURAÇÃO DE PROJETOS E FATIAS
# ==========================================
@router.post("/videos/{video_id}/slices/auto")
def create_auto_slices(video_id: int, slice_in: dict, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == video_id).first()
    
    def time_to_sec(t_str):
        h, m = map(int, t_str.split(':'))
        return h * 3600 + m * 60
        
    def sec_to_time(sec):
        h = (sec // 3600) % 24
        m = (sec % 3600) // 60
        return f"{h:02d}:{m:02d}"

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
    return {"message": f"{len(slices)} fatias criadas."}

@router.post("/projects/{project_id}/config")
def save_project_config(project_id: int, payload: schemas.ProjectConfigCreate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project: raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    
    nomes_zonas_vivas = {z.name.strip() for z in payload.zones}
    movimentos_validados = []
    for mov_str in payload.movements:
        partes = mov_str.split(" ➔ ") if " ➔ " in mov_str else mov_str.split(" -> ")
        if len(partes) == 2:
            origem, destino = partes[0].strip(), partes[1].strip()
            if origem in nomes_zonas_vivas and destino in nomes_zonas_vivas:
                movimentos_validados.append(mov_str)

    db.query(Zone).filter(Zone.project_id == project_id).delete(synchronize_session=False)
    for zone_in in payload.zones:
        db.add(Zone(project_id=project_id, name=zone_in.name, geometry_data=json.dumps(zone_in.geometry)))
        
    movimentos_atuais_db = db.query(Movement).filter(Movement.project_id == project_id).all()
    mapa_db = {m.name: m for m in movimentos_atuais_db}
    set_novos = set(movimentos_validados)
    
    for nome_db, mov_obj in mapa_db.items():
        if nome_db not in set_novos:
            tarefas = db.query(MovementTask).filter(MovementTask.movement_id == mov_obj.id).all()
            ids_t = [t.id for t in tarefas]
            if ids_t:
                db.query(CountRecord).filter(CountRecord.task_id.in_(ids_t)).delete(synchronize_session=False)
                db.query(MovementTask).filter(MovementTask.id.in_(ids_t)).delete(synchronize_session=False)
            db.delete(mov_obj)
            
    novos_mov_objs = []
    for nome_n in set_novos:
        if nome_n not in mapa_db:
            nm = Movement(project_id=project_id, name=nome_n)
            db.add(nm)
            novos_mov_objs.append(nm)
            
    db.flush() 
    
    if novos_mov_objs:
        videos_ativos = db.query(Video).filter(Video.project_id == project_id, Video.status.in_([VideoStatus.approved, "approved", "completed"])).all()
        for v in videos_ativos:
            for fatia in v.slices:
                for nm in novos_mov_objs:
                    db.add(MovementTask(slice_id=fatia.id, movement_id=nm.id, status="pending"))

    db.query(Video).filter(Video.project_id == project_id, Video.status == VideoStatus.ready).update({"status": VideoStatus.configured}, synchronize_session=False)
    db.commit()
    return {"message": "Configuração sincronizada!"}

@router.patch("/projects/{project_id}/approve")
def approve_project_for_ai(project_id: int, db: Session = Depends(get_db)):
    from models import Project, Video, VideoSlice, MovementTask, VideoStatus, SliceStatus
    
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project or not project.movements:
        raise HTTPException(status_code=400, detail="Desenhe as zonas e salve os Movimentos!")
        
    # 🔴 FIX: Busca de forma flexível (tanto configured quanto ready)
    videos = db.query(Video).filter(
        Video.project_id == project_id, 
        Video.status.in_([VideoStatus.configured, "configured", VideoStatus.ready, "ready"])
    ).all()
    
    if not videos:
        raise HTTPException(status_code=400, detail="Nenhum vídeo válido encontrado para avançar.")

    for v in videos:
        slices_to_process = v.slices
        if not slices_to_process:
            fatia = VideoSlice(video_id=v.id, name="Vídeo Completo", start_time=0, end_time=0, nominal_duration=0)
            db.add(fatia)
            db.flush()
            slices_to_process = [fatia]
            
        for sl in slices_to_process:
            for mov in project.movements:
                # Prevenção extra: só cria a tarefa se ela não existir, evitando duplicações no vai-e-vem
                existe = db.query(MovementTask).filter(MovementTask.slice_id == sl.id, MovementTask.movement_id == mov.id).first()
                if not existe:
                    db.add(MovementTask(slice_id=sl.id, movement_id=mov.id, status=SliceStatus.pending))
                    
        # Avança o status oficialmente usando o Enum correto
        v.status = VideoStatus.approved
        
    db.commit()
    return {"message": "Vídeos liberados e Matriz gerada!"}

# ==========================================
# ALOCAÇÃO DE FREELANCERS
# ==========================================
@router.get("/admin/allocation", response_class=HTMLResponse)
def allocation_page(request: Request):
    return templates.TemplateResponse(request=request, name="allocation.html")

@router.get("/allocation/data")
def get_allocation_data(db: Session = Depends(get_db)):
    from sqlalchemy import text 
    from models import User, Video, VideoStatus, WorkPackage
    
    db.execute(text("UPDATE videos SET status = 'processing' WHERE status = 'recounting'"))
    db.commit()

    freelas = db.query(User).filter(User.role == "freelancer").all()
    
    videos = db.query(Video).filter(
        Video.status.in_([
            VideoStatus.processing, "processing", 
            VideoStatus.configured, "configured"
        ])
    ).all()

    video_list = []
    for v in videos:
        slices_data = []
        # 🔴 NOVA INTELIGÊNCIA: Rastreador de pendências no vídeo
        tem_pendencia_no_video = False 

        for sl in v.slices:
            tasks_data = []
            for t in sl.tasks:
                status_valor = t.status.value if hasattr(t.status, 'value') else str(t.status).replace("SliceStatus.", "")
                
                # Ignora as que a IA matou
                if status_valor == "completed" and t.assigned_to is None:
                    continue
                
                # 🔴 SE ACHOU QUALQUER COISA QUE NÃO ESTEJA CONCLUÍDA (pending, assigned, etc.)
                # Então esse vídeo precisa ir pra tela!
                if status_valor != "completed":
                    tem_pendencia_no_video = True
                
                freela_name = None
                if t.assigned_to:
                    user_obj = db.query(User).filter(User.id == t.assigned_to).first()
                    if user_obj: freela_name = user_obj.name
                
                package_name = None
                if getattr(t, 'work_package_id', None):
                    pacote = db.query(WorkPackage).filter(WorkPackage.id == t.work_package_id).first()
                    if pacote: package_name = pacote.name
                
                tasks_data.append({
                    "id": t.id,
                    "movement_name": t.movement.name if t.movement else "Movimento",
                    "status": status_valor,
                    "freelancer_name": freela_name,
                    "package_name": package_name
                })
            
            if len(tasks_data) > 0:
                slices_data.append({
                    "id": sl.id, "name": sl.name, "start_time": sl.start_time, "end_time": sl.end_time,
                    "tasks": tasks_data, "videoId": v.id, "filename": v.original_filename
                })
            
        # TRAVA ATUALIZADA: Envia o vídeo se houver qualquer fatia filtrada, 
        # permitindo listar as tarefas concluídas na aba de baixo!
        if len(slices_data) > 0:
            video_list.append({
                "id": v.id, 
                "filename": v.original_filename, 
                "project_name": v.project.name if v.project else "Sem Projeto", 
                "client_name": v.project.client.name if v.project and v.project.client else "Sem Cliente",
                "slices": slices_data
            })
        
    return {
        "freelancers": [{"id": f.id, "name": f.name} for f in freelas],
        "videos": video_list
    }

@router.patch("/slices/{slice_id}/assign")
def assign_slice(slice_id: int, payload: dict, db: Session = Depends(get_db)):
    v_slice = db.query(VideoSlice).filter(VideoSlice.id == slice_id).first()
    if not v_slice: raise HTTPException(status_code=404, detail="Fatia não encontrada.")
    v_slice.assigned_to = payload.get("user_id")
    v_slice.status = SliceStatus.assigned
    if v_slice.video.status == VideoStatus.approved:
        v_slice.video.status = VideoStatus.processing
    db.commit()
    return {"message": "Fatia atribuída."}

@router.patch("/tasks/assign_bulk")
def assign_tasks_bulk(payload: AssignTasksPayload, db: Session = Depends(get_db)):
    tasks = db.query(MovementTask).filter(MovementTask.id.in_(payload.task_ids)).all()
    for t in tasks:
        t.assigned_to = payload.user_id
        t.status = SliceStatus.assigned
        if t.video_slice.video.status == VideoStatus.approved:
            t.video_slice.video.status = VideoStatus.processing
    db.commit()
    return {"message": f"{len(tasks)} tarefas atribuídas."}

@router.post("/api/admin/work-packages")
def create_work_package(payload: CreateWorkPackageRequest, db: Session = Depends(get_db)):
    primeira_tarefa = db.query(MovementTask).filter(MovementTask.id == payload.task_ids[0]).first()
    
    # Se nem a primeira tarefa for achada, os IDs já estão velhos
    if not primeira_tarefa:
        raise HTTPException(status_code=400, detail="As tarefas selecionadas não existem mais no banco. Por favor, atualize a página (F5).")
        
    fatia = db.query(VideoSlice).filter(VideoSlice.id == primeira_tarefa.slice_id).first() if primeira_tarefa else None
    video = db.query(Video).filter(Video.id == fatia.video_id).first() if fatia else None
    projeto_id = video.project_id if video else None

    if not projeto_id: raise HTTPException(status_code=400, detail="Tarefas órfãs sem projeto.")

    pacote_existente = db.query(WorkPackage).filter(
        WorkPackage.freelancer_id == payload.freelancer_id, WorkPackage.project_id == projeto_id, WorkPackage.status != "completed"
    ).first()

    if pacote_existente:
        pacote_ativo_id = pacote_existente.id
        if payload.name and payload.name.strip() != "":
            pacote_existente.name = payload.name
        db.flush()
    else:
        nome_pacote = payload.name if payload.name.strip() != "" else f"Lote de Trabalho - Projeto #{projeto_id}"
        novo_pacote = WorkPackage(name=nome_pacote, freelancer_id=payload.freelancer_id, project_id=projeto_id, status="pending")
        db.add(novo_pacote)
        db.flush()
        pacote_ativo_id = novo_pacote.id
    
    # 🔴 TRAVA DE SEGURANÇA: Salva a quantidade de linhas que o banco atualizou
    linhas_atualizadas = db.query(MovementTask).filter(MovementTask.id.in_(payload.task_ids)).update({
        "work_package_id": pacote_ativo_id, "assigned_to": payload.freelancer_id, "status": "pending"
    }, synchronize_session=False)
    
    # Se o banco não atualizou ninguém, é porque os checkboxes mandaram fantasmas!
    if linhas_atualizadas == 0:
        db.rollback() # Cancela a criação do pacote
        raise HTTPException(status_code=400, detail="Nenhuma tarefa atualizada. Atualize a página de Alocação e tente novamente.")
        
    db.commit()
    
    msg = "Tarefas adicionadas ao lote existente!" if pacote_existente else "Novo Lote criado!"
    return {"message": msg, "package_id": pacote_ativo_id}

@router.patch("/videos/{video_id}/toggle-validation")
def toggle_video_validation(video_id: int, db: Session = Depends(get_db)):
    from models import Video, VideoSlice, MovementTask # Garanta que os modelos estão importados
    
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    
    # Inverte o status
    video.is_validation = not video.is_validation
    
    # 🔴 LÓGICA DE LIMPEZA:
    # Se você acabou de DESMARCAR a validação, precisamos desatribuir os freelas
    if video.is_validation is False:
        # Busca todas as fatias desse vídeo
        slice_ids = [s.id for s in video.slices]
        
        if slice_ids:
            # Busca todas as tarefas dessas fatias e limpa o campo assigned_to e work_package
            db.query(MovementTask).filter(
                MovementTask.slice_id.in_(slice_ids)
            ).update({
                "assigned_to": None,
                "work_package_id": None
            }, synchronize_session=False)
            
    db.commit()
    
    return {
        "message": "Status atualizado e atribuições limpas", 
        "is_validation": video.is_validation
    }

@router.patch("/videos/{video_id}/revert") 
def revert_video_to_staging(video_id: int, db: Session = Depends(get_db)):
    from models import Video, VideoSlice, MovementTask, CountRecord, VideoStatus
    
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado")
        
    for fatia in video.slices:
        tarefas_ids = [t.id for t in fatia.tasks]
        if tarefas_ids:
            db.query(CountRecord).filter(CountRecord.task_id.in_(tarefas_ids)).delete(synchronize_session=False)
        db.query(MovementTask).filter(MovementTask.slice_id == fatia.id).delete(synchronize_session=False)
        
    db.query(VideoSlice).filter(VideoSlice.video_id == video.id).delete(synchronize_session=False)
    
    # 🔴 FIX: Limpa a flag de validação e usa o Enum correto pro status
    video.status = VideoStatus.ready 
    video.is_validation = False
    
    db.commit()
    return {"message": "Vídeo revertido e limpo com sucesso!"}


# ==========================================
# RELATÓRIOS
# ==========================================
@router.get("/admin/reports", response_class=HTMLResponse)
def view_reports_page(request: Request):
    return templates.TemplateResponse(request=request, name="reports.html")

@router.get("/api/admin/reports/completed")
def get_completed_reports(db: Session = Depends(get_db)):
    from models import Project, Client
    
    # Busca apenas projetos aprovados, ordenados do mais recente para o mais antigo
    projetos_aprovados = db.query(Project)\
        .join(Client)\
        .filter(Project.status.in_(["approved", "completed"]))\
        .order_by(Project.id.desc())\
        .all()
        
    # Agrupa por Cliente mantendo a ordem do projeto mais recente
    clientes_agrupados = {}
    
    for proj in projetos_aprovados:
        cliente_nome = proj.client.name if proj.client else "Sem Cliente"
        
        if cliente_nome not in clientes_agrupados:
            clientes_agrupados[cliente_nome] = {
                "client_name": cliente_nome,
                "projects": []
            }
            
        clientes_agrupados[cliente_nome]["projects"].append({
            "project_id": proj.id,
            "project_name": proj.name,
            # Se você salvou os dados finais no projeto, pode enviá-cols aqui:
            "final_data": proj.audit_selections # ou proj.final_report_data
        })
        
    # Transforma o dicionário em uma lista para o frontend
    return {"status": "success", "data": list(clientes_agrupados.values())}


@router.get("/api/admin/reports/{project_id}")
def get_project_report(project_id: int, db: Session = Depends(get_db), approved_only: bool = False):
    import re
    import random 
    from models import Project, Video, VideoSlice, Movement, MovementTask, CountRecord
    
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project: raise HTTPException(status_code=404, detail="Projeto não encontrado")
        
    movements = db.query(Movement).filter(Movement.project_id == project_id).all()
    videos = db.query(Video).filter(Video.project_id == project_id).all()
    video_ids = [v.id for v in videos]
    slices = db.query(VideoSlice).filter(VideoSlice.video_id.in_(video_ids)).all()
    
    report_dict = {}

    # 🔴 A sub-função com a indentação corrigida
    def preencher_esqueleto(fatia, mov_name):
        tarefa_id = None
        if hasattr(fatia, 'tasks') and fatia.tasks:
            for t in fatia.tasks:
                if t.movement and t.movement.name == mov_name:
                    tarefa_id = t.id
                    break

        match = re.search(r'(\d{2}):(\d{2})', fatia.name)
        h_start, m_start = (int(match.group(1)), int(match.group(2))) if match else (0,0)
        duracao_segundos = fatia.end_time - fatia.start_time
        num_blocos = int(duracao_segundos // 900) or 1
        
        for i in range(num_blocos):
            min_base = h_start * 60 + m_start + (i * 15)
            h_in, m_in = (min_base // 60) % 24, min_base % 60
            h_out, m_out = ((min_base + 15) // 60) % 24, (min_base + 15) % 60
            txt = f"{h_in:02d}:{m_in:02d} - {h_out:02d}:{m_out:02d}"
            chave = f"{fatia.video.original_filename}|{fatia.id}|{mov_name}|{txt}"
            
            if chave not in report_dict:
                mock_ia = {
                    "Carro": random.randint(10, 50),
                    "Moto": random.randint(2, 15),
                    "Ônibus": random.randint(0, 5),
                    "Caminhão": random.randint(0, 8)
                }
                
                report_dict[chave] = {
                    "video": fatia.video.original_filename, 
                    "slice_id": fatia.id,
                    "movement": mov_name, 
                    "task_id": tarefa_id, # 🔴 Aqui vai entrar o número perfeito!
                    "interval": txt, 
                    "sort_key": min_base, 
                    "Carro": None,  
                    "Moto": None,   
                    "Ônibus": None, 
                    "Caminhão": None, 
                    "ia_data": mock_ia, 
                    "has_data": False,
                    "is_sample": False 
                }

    # Resto do seu código que chama a função...
    for mov in movements:
        for s in slices:
            preencher_esqueleto(s, mov.name)

    slice_ids = [s.id for s in slices]
    tasks = db.query(MovementTask).filter(MovementTask.slice_id.in_(slice_ids)).all()
    
    slice_map = {s.id: s for s in slices}
    video_map = {v.id: v for v in videos}

    # 🔴 NOVO: Verifica quais tarefas foram enviadas pro Freela e marca o bloco como Amostra
    for t in tasks:
        if t.assigned_to is not None:
            fatia = slice_map.get(t.slice_id)
            if not fatia: continue
            video = video_map.get(fatia.video_id)
            mov_name = t.movement.name if t.movement else "Indefinido"
            
            match = re.search(r'(\d{2}):(\d{2})', fatia.name)
            h_start, m_start = (int(match.group(1)), int(match.group(2))) if match else (0,0)
            duracao_segundos = fatia.end_time - fatia.start_time
            num_blocos = int(duracao_segundos // 900) or 1
            
            for i in range(num_blocos):
                min_base = h_start * 60 + m_start + (i * 15)
                h_in, m_in = (min_base // 60) % 24, min_base % 60
                h_out, m_out = ((min_base + 15) // 60) % 24, (min_base + 15) % 60
                txt = f"{h_in:02d}:{m_in:02d} - {h_out:02d}:{m_out:02d}"
                chave = f"{video.original_filename}|{fatia.id}|{mov_name}|{txt}"
                
                if chave in report_dict:
                    report_dict[chave]["is_sample"] = True

    # Busca os cliques do humano
    query_records = db.query(CountRecord).join(MovementTask).filter(MovementTask.slice_id.in_(slice_ids))
    if approved_only:
        query_records = query_records.filter(CountRecord.is_approved == True)
    records = query_records.all()

    task_map = {t.id: t for t in tasks}

    for r in records:
        t = task_map.get(r.task_id)
        if not t: continue
            
        fatia = slice_map.get(t.slice_id)
        video = video_map.get(fatia.video_id)
        mov_name = t.movement.name if t.movement else "Indefinido"
        
        bloco_idx = int(r.video_time // 900)
        match = re.search(r'(\d{2}):(\d{2})', fatia.name)
        if match:
            min_i = int(match.group(1)) * 60 + int(match.group(2)) + (bloco_idx * 15)
            txt = f"{(min_i // 60) % 24:02d}:{min_i % 60:02d} - {((min_i + 15) // 60) % 24:02d}:{(min_i + 15) % 60:02d}"
            
            chave = f"{video.original_filename}|{fatia.id}|{mov_name}|{txt}"
            
            if chave in report_dict:
                if report_dict[chave][r.vehicle_class] is None:
                    report_dict[chave][r.vehicle_class] = 0
                report_dict[chave][r.vehicle_class] += 1
                report_dict[chave]["has_data"] = True

    if approved_only and not any(v["has_data"] for v in report_dict.values()):
        return {"project_name": project.name, "client_name": project.client.name, "data": []}

    resultado_final = list(report_dict.values())
    resultado_final.sort(key=lambda x: (x['movement'], x['sort_key'], x['video']))
    
    project_status = getattr(project, 'status', 'processing')
    selections = getattr(project, 'audit_selections', {})

    return {
        "project_name": project.name,
        "client_name": project.client.name if project.client else "Sem Cliente",
        "status": project_status, 
        "audit_selections": selections,
        "data": resultado_final
    }

@router.get("/api/admin/projects/{project_id}/consolidated")
def get_consolidated_report(project_id: int, db: Session = Depends(get_db)):
    from models import Project, ConsolidatedReport
    
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")

    # Busca todos os registros consolidados
    records = db.query(ConsolidatedReport).filter(ConsolidatedReport.project_id == project_id).all()
    
    # Formata os dados para o frontend (agrupando por movimento e intervalo)
    # Estrutura similar ao que a Auditoria usa, mas simplificada
    data_list = []
    for r in records:
        data_list.append({
            "movement": r.movement_name,
            "interval": r.interval,
            "category": r.category,
            "count": r.count,
            "source": r.source
        })

    return {
        "project_name": project.name,
        "client_name": project.client.name if project.client else "N/A",
        "data": data_list
    }

@router.get("/api/admin/projects/{project_id}/export")
def export_project_excel(project_id: int, db: Session = Depends(get_db)):
    from models import Project, ConsolidatedReport
    
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")

    # 1. Busca os dados consolidados no banco
    records = db.query(ConsolidatedReport).filter(ConsolidatedReport.project_id == project_id).all()
    if not records:
        raise HTTPException(status_code=400, detail="Este projeto ainda não possui dados consolidados para exportação.")

    # 2. Converte para um DataFrame do Pandas
    data = [{
        "Movimento": r.movement_name,
        "Intervalo": r.interval,
        "Categoria": r.category,
        "Quantidade": r.count
    } for r in records]
    df_raw = pd.DataFrame(data)

    # 3. Cria o arquivo Excel em memória (Buffer)
    output = io.BytesIO()
    
    # Ordem desejada das colunas
    ordem_categorias = ["Carro", "Moto", "Ônibus", "Caminhão"]

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for movement in df_raw['Movimento'].unique():
            # Filtra os dados deste movimento
            df_mov = df_raw[df_raw['Movimento'] == movement]
            
            # Transforma as categorias em colunas (Pivot)
            df_pivot = df_mov.pivot(index='Intervalo', columns='Categoria', values='Quantidade').fillna(0)
            
            # Garante que todas as categorias existam e estejam na ordem certa
            for cat in ordem_categorias:
                if cat not in df_pivot.columns:
                    df_pivot[cat] = 0
            
            df_pivot = df_pivot[ordem_categorias]
            
            # Adiciona coluna de Total por linha
            df_pivot['Total'] = df_pivot.sum(axis=1)
            
            # Nome da aba (limite de 31 caracteres do Excel)
            sheet_name = str(movement)[:31].replace("/", "-").replace("\\", "-")
            
            # Salva no Excel
            df_pivot.to_excel(writer, sheet_name=sheet_name)

    output.seek(0)
    
    # 4. Retorna o arquivo para o navegador
    filename = f"Relatorio_{project.name.replace(' ', '_')}.xlsx"
    headers = {'Content-Disposition': f'attachment; filename="{filename}"'}
    
    return StreamingResponse(
        output, 
        headers=headers, 
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

# ==========================================
# DASHBOARD (TORRE DE CONTROLE)
# ==========================================
@router.get("/admin/dashboard", response_class=HTMLResponse)
def render_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html")

@router.get("/admin/freelancers", response_class=HTMLResponse)
def render_freelancers(request: Request):
    return templates.TemplateResponse(request=request, name="freelancers.html")

@router.get("/admin/audit", response_class=HTMLResponse)
def render_audit_page(request: Request):
    return templates.TemplateResponse(request=request, name="audit.html")

# ==========================================
# ESTATÍSTICAS GLOBAIS (SIDEBAR E DASHBOARD)
# ==========================================

@router.get("/api/admin/sidebar-stats")
def get_sidebar_stats(db: Session = Depends(get_db)):
    from models import Video, VideoStatus, MovementTask, SliceStatus, VideoSlice, Project
    
    # 🔴 1. GATILHO AUTOMÁTICO: Libera projetos "recounting" que os freelas já terminaram!
    projetos_em_recontagem = db.query(Project).filter(Project.status == "recounting").all()
    for proj in projetos_em_recontagem:
        # Conta se ainda existe alguma tarefa pendente ou em andamento neste projeto
        tarefas_incompletas = db.query(MovementTask).join(VideoSlice).join(Video).filter(
            Video.project_id == proj.id,
            MovementTask.status.in_(["pending", "assigned", SliceStatus.pending, SliceStatus.assigned])
        ).count()
        
        # Se não sobrou nada pendente, o freela terminou! Devolve pra auditoria.
        if tarefas_incompletas == 0:
            proj.status = "processing"
            
    db.commit() # Salva a auto-liberação no banco

    # ... RESTO DA FUNÇÃO CONTINUA IGUAL ...
    
    # Pendências de Staging
    staged_count = db.query(Video).filter(
        Video.status.in_([VideoStatus.staged, VideoStatus.ready, VideoStatus.configured])
    ).count()
    
    # Pendências de Alocação
    pending_tasks = db.query(MovementTask)\
        .join(VideoSlice)\
        .join(Video)\
        .filter(
            MovementTask.status.in_([SliceStatus.pending, SliceStatus.assigned, "pending", "assigned"]),
            Video.status.in_([VideoStatus.processing, "processing", VideoStatus.configured, "configured"])
        ).count()
    
    # Pendências de Auditoria
    audit_ready = db.query(MovementTask)\
        .join(VideoSlice)\
        .join(Video)\
        .join(Project, Video.project_id == Project.id)\
        .filter(
            MovementTask.status.in_([SliceStatus.completed, "completed"]),
            Project.status.notin_(["recounting", "approved", "completed"]),
            Video.status.in_([VideoStatus.processing, "processing", VideoStatus.configured, "configured"])
        ).count()
    
    return {
        "staging": staged_count,
        "allocation": pending_tasks,
        "audit": audit_ready
    }

@router.get("/api/admin/kanban-data")
def get_kanban_data(db: Session = Depends(get_db)):
    from models import Project, Video, VideoStatus, MovementTask, SliceStatus
    
    projetos = db.query(Project).all()
    resultado = []
    
    for p in projetos:
        # Contagem de tarefas para progresso
        videos_ids = [v.id for v in p.videos]
        slices = db.query(VideoSlice).filter(VideoSlice.video_id.in_(videos_ids)).all()
        slice_ids = [s.id for s in slices]
        
        total_tasks = db.query(MovementTask).filter(MovementTask.slice_id.in_(slice_ids)).count()
        done_tasks = db.query(MovementTask).filter(
            MovementTask.slice_id.in_(slice_ids), 
            MovementTask.status == SliceStatus.completed
        ).count()
        
        # Determina o estágio principal do projeto
        estagio = "staging"
        if any(v.status == VideoStatus.approved for v in p.videos): estagio = "allocation"
        if total_tasks > 0 and done_tasks == total_tasks: estagio = "completed"
        
        resultado.append({
            "id": p.id,
            "name": p.name,
            "client": p.client.name if p.client else "N/A",
            "progress": f"{done_tasks}/{total_tasks}",
            "percent": int((done_tasks / total_tasks * 100)) if total_tasks > 0 else 0,
            "stage": estagio
        })
    return resultado


# ==========================================
# AUDITORIA (IA vs HUMANO)
# ==========================================
@router.post("/api/admin/projects/{project_id}/audit/approve")
def approve_audit(project_id: int, payload: dict, db: Session = Depends(get_db)):
    from models import Project, ConsolidatedReport
    
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")

    final_data = payload.get("final_data", [])
    selections_map = payload.get("selections_map", {})

    if not final_data:
        raise HTTPException(status_code=400, detail="Nenhum dado para salvar.")

    # 1. Salva a "Foto" da UI para re-auditoria futura
    project.audit_selections = selections_map
    project.status = "approved"
    
    videos = db.query(Video).filter(Video.project_id == project.id).all()
    for v in videos:
        v.status = "approved"

    # 2. Sobrescreve os dados finais
    db.query(ConsolidatedReport).filter(ConsolidatedReport.project_id == project_id).delete()
    
    for row in final_data:
        novo_registro = ConsolidatedReport(
            project_id=project_id,
            movement_name=row["movement"],
            interval=row["interval"],
            category=row["category"],
            count=row["count"],
            source=row["source"]
        )
        db.add(novo_registro)

    db.commit()
    return {"message": "Auditoria consolidada e salva com sucesso!"}

class RecountPayload(BaseModel):
    selections: Dict[str, str]
    keep_tasks: List[int] # 🔴 AGORA SÃO APENAS NÚMEROS!

@router.post("/api/admin/projects/{project_id}/confirm-recount")
def confirm_recount(project_id: int, payload: dict, db: Session = Depends(get_db)):
    from models import Project, Video, VideoSlice, MovementTask, SliceStatus
    import math

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return {"status": "error", "message": "Projeto não encontrado"}

    # 1. O projeto muda para o status de recontagem
    project.status = "recounting"

    # Captura os horários que você selecionou no modal
    start_time_raw = payload.get("start_time", 0)
    end_time_raw = payload.get("end_time", 0)

    # 🔴 ARREDONDAMENTO: Transforma qualquer minuto quebrado em janelas de 1h cheia (3600 segundos)
    start_time_cheio = math.floor(start_time_raw / 3600) * 3600
    end_time_cheio = math.ceil(end_time_raw / 3600) * 3600

    # Busca os vídeos atrelados a esse projeto
    videos = db.query(Video).filter(Video.project_id == project_id).all()
    
    for v in videos:
        # O vídeo volta a ficar "processing" para reaparecer na esteira de alocação
        v.status = "processing" 
        
        # Busca as fatias de 1 hora que intersectam o horário que você mandou recontar
        slices = db.query(VideoSlice).filter(
            VideoSlice.video_id == v.id,
            VideoSlice.start_time >= start_time_cheio,
            VideoSlice.end_time <= end_time_cheio
        ).all()

        for sl in slices:
            for t in sl.tasks:
                # 🔴 OBRIGATÓRIO PARA IR PARA A ABA "PENDENTES":
                # Tiramos o status de concluído e jogamos para pendente
                t.status = "pending"          # Ou SliceStatus.pending se o seu modelo usar o Enum
                
                # Desvinculamos o freelancer antigo para que a tarefa fique "sem dono"
                t.assigned_to = None          
                
                # Se o seu modelo tiver um campo 'work_package_id', limpe ele também para desvincular do pacote antigo:
                if hasattr(t, 'work_package_id'):
                    t.work_package_id = None

    # Salva todas as alterações de vez no banco de dados
    db.commit() 
    
    return {"status": "success", "message": "Tarefas resetadas com sucesso para horas cheias."}


@router.post("/api/admin/projects/{project_id}/audit/revert")
def revert_audit(project_id: int, db: Session = Depends(get_db)):
    from models import Project, Video
    
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return {"status": "error", "message": "Projeto não encontrado"}
    
    # 🔴 Devolve o projeto para processamento. 
    # Como as tarefas já estão "completed", ele cai magicamente de volta na fila de Auditoria!
    project.status = "processing"
    
    # Faz o mesmo com os vídeos atrelados
    videos = db.query(Video).filter(Video.project_id == project.id).all()
    for v in videos:
        v.status = "processing"
        
    db.commit()
    
    return {"status": "success", "message": "Projeto devolvido para auditoria."}







# --------------------------- rota temporária para resetar as alocações e tarefas, útil durante os testes ---------------------------
@router.get("/api/admin/debug/reset-allocations")
def reset_all_allocations(db: Session = Depends(get_db)):
    from models import MovementTask, WorkPackage, CountRecord
    
    # 1. Apaga todos os registros de contagem (opcional, remova se não quiser perder o que o freela já contou no teste)
    db.query(CountRecord).delete(synchronize_session=False)
    
    # 2. Desatribui todas as tarefas de todos os freelas e volta para pendente
    db.query(MovementTask).update({
        "assigned_to": None,
        "work_package_id": None,
        "status": "pending"
    }, synchronize_session=False)
    
    # 3. Apaga os pacotes de trabalho (WorkPackages)
    db.query(WorkPackage).delete(synchronize_session=False)
    
    db.commit()
    return {"message": "🧹 Faxina completa! O workspace de todos os freelancers está limpo e todas as tarefas voltaram para o zero."}