import os
import json
import re
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db
from models import (Project, Zone, Movement, Video, VideoStatus, MovementTask, 
                    CountRecord, VideoSlice, SliceStatus, Client, User, WorkPackage)
from web import schemas

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
        Video.status.in_([VideoStatus.staged, VideoStatus.ready, VideoStatus.configured])
    ).all()
    
    for v in videos:
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

@router.patch("/videos/{video_id}/revert") 
def revert_video_to_staging(video_id: int, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado")
        
    for fatia in video.slices:
        tarefas_ids = [t.id for t in fatia.tasks]
        if tarefas_ids:
            db.query(CountRecord).filter(CountRecord.task_id.in_(tarefas_ids)).delete(synchronize_session=False)
        db.query(MovementTask).filter(MovementTask.slice_id == fatia.id).delete(synchronize_session=False)
        
    db.query(VideoSlice).filter(VideoSlice.video_id == video.id).delete(synchronize_session=False)
    video.status = "ready" 
    db.commit()
    return {"message": "Vídeo revertido e limpo com sucesso!"}

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
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project or not project.movements:
        raise HTTPException(status_code=400, detail="Desenhe as zonas e salve os Movimentos!")
        
    videos = db.query(Video).filter(Video.project_id == project_id, Video.status == VideoStatus.configured).all()
    for v in videos:
        slices_to_process = v.slices
        if not slices_to_process:
            fatia = VideoSlice(video_id=v.id, name="Vídeo Completo", start_time=0, end_time=0, nominal_duration=0)
            db.add(fatia)
            db.flush()
            slices_to_process = [fatia]
            
        for sl in slices_to_process:
            for mov in project.movements:
                db.add(MovementTask(slice_id=sl.id, movement_id=mov.id, status=SliceStatus.pending))
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
    freelas = db.query(User).filter(User.role == "freelancer").all()
    videos = db.query(Video).filter(Video.status.in_([VideoStatus.approved, VideoStatus.configured, "approved"])).all()
    
    video_list = []
    for v in videos:
        slices_data = []
        for sl in v.slices:
            tasks_data = []
            for t in sl.tasks:
                freela_name = None
                if t.assigned_to:
                    user_obj = db.query(User).filter(User.id == t.assigned_to).first()
                    if user_obj: freela_name = user_obj.name
                
                package_name = None
                if getattr(t, 'work_package_id', None):
                    pacote = db.query(WorkPackage).filter(WorkPackage.id == t.work_package_id).first()
                    if pacote: package_name = pacote.name
                
                status_valor = t.status.value if hasattr(t.status, 'value') else str(t.status).replace("SliceStatus.", "")
                
                tasks_data.append({
                    "id": t.id,
                    "movement_name": t.movement.name if t.movement else "Movimento",
                    "status": status_valor,
                    "freelancer_name": freela_name,
                    "package_name": package_name
                })
            
            slices_data.append({
                "id": sl.id, "name": sl.name, "start_time": sl.start_time, "end_time": sl.end_time,
                "tasks": tasks_data, "videoId": v.id, "filename": v.original_filename
            })
            
        video_list.append({
            "id": v.id, "filename": v.original_filename, "project_name": v.project.name if v.project else "Sem Projeto", "slices": slices_data
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
    
    db.query(MovementTask).filter(MovementTask.id.in_(payload.task_ids)).update({
        "work_package_id": pacote_ativo_id, "assigned_to": payload.freelancer_id, "status": "pending"
    }, synchronize_session=False)
    db.commit()
    
    msg = "Tarefas adicionadas ao lote existente!" if pacote_existente else "Novo Lote criado!"
    return {"message": msg, "package_id": pacote_ativo_id}

# ==========================================
# RELATÓRIOS
# ==========================================
@router.get("/admin/reports", response_class=HTMLResponse)
def view_reports_page(request: Request):
    return templates.TemplateResponse(request=request, name="reports.html")

@router.get("/api/admin/reports/{project_id}")
def get_project_report(project_id: int, db: Session = Depends(get_db)):

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project: raise HTTPException(status_code=404, detail="Projeto não encontrado")
        
    videos = db.query(Video).filter(Video.project_id == project_id).all()
    video_ids = [v.id for v in videos]
    slices = db.query(VideoSlice).filter(VideoSlice.video_id.in_(video_ids)).all()
    slice_ids = [s.id for s in slices]
    # Agora pegamos TODAS as tarefas, independentemente do status (WIP incluído)
    tasks = db.query(MovementTask).filter(MovementTask.slice_id.in_(slice_ids)).all()

    task_ids = [t.id for t in tasks]
    records = db.query(CountRecord).filter(CountRecord.task_id.in_(task_ids)).all()
    
    task_map = {t.id: t for t in tasks}
    video_map = {v.id: v for v in videos}
    slice_map = {s.id: s for s in slices}
    report_dict = {}
    
    for r in records:
        task = task_map.get(r.task_id)
        if not task: continue
        fatia = slice_map.get(task.slice_id)
        video = video_map.get(fatia.video_id)
        
        mov_name = task.movement.name if task.movement else "Indefinido"
        video_filename = video.original_filename
        
        bloco_idx = int(r.video_time // 900)
        
        # 🔴 A MÁGICA: Converte minutos relativos na Hora Real baseada na Fatia
        match = re.search(r'(\d{2}):(\d{2})', fatia.name)
        if match:
            h = int(match.group(1))
            m = int(match.group(2))
            minutos_inicio = h * 60 + m + (bloco_idx * 15)
            minutos_fim = minutos_inicio + 15
            
            h_in = (minutos_inicio // 60) % 24
            m_in = minutos_inicio % 60
            h_out = (minutos_fim // 60) % 24
            m_out = minutos_fim % 60
            
            intervalo_txt = f"{h_in:02d}:{m_in:02d} - {h_out:02d}:{m_out:02d}"
            chave_ordem = minutos_inicio # Chave mestre para cronologia perfeita!
        else:
            # Fallback caso a fatia não tenha hora no nome
            intervalo_txt = f"{str(bloco_idx * 15).zfill(2)}m - {str((bloco_idx + 1) * 15).zfill(2)}m"
            chave_ordem = bloco_idx
            
        # A chave de agrupamento garante que fatias iguais não se sobreponham
        chave = f"{video_filename}|{fatia.id}|{mov_name}|{intervalo_txt}"
        
        if chave not in report_dict:
            report_dict[chave] = {
                "video": video_filename,
                "movement": mov_name,
                "interval": intervalo_txt,
                "sort_key": chave_ordem,
                "Carro": 0, "Moto": 0, "Ônibus": 0, "Caminhão": 0
            }
        
        classe = r.vehicle_class
        if classe in report_dict[chave]:
            report_dict[chave][classe] += 1
            
    # 🔴 ORDENAÇÃO BLINDADA: Por Movimento -> Tempo Absoluto -> Nome do Vídeo
    resultado_final = list(report_dict.values())
    resultado_final.sort(key=lambda x: (x['movement'], x['sort_key'], x['video']))
    
    return {
        "project_name": project.name, "client_name": project.client.name if project.client else "N/A", "data": resultado_final
    }

# ==========================================
# DASHBOARD (TORRE DE CONTROLE)
# ==========================================
@router.get("/admin/dashboard", response_class=HTMLResponse)
def render_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html")

@router.get("/admin/freelancers", response_class=HTMLResponse)
def render_freelancers(request: Request):
    return templates.TemplateResponse(request=request, name="freelancers.html")