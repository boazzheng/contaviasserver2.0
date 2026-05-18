import os
import re
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel

from database import get_db
from models import (User, WorkPackage, MovementTask, SliceStatus, VideoSlice, Video, CountRecord)

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# --- MODELOS INLINE ---
class RecordItem(BaseModel):
    vehicle_class: str
    video_time: float

class CompleteTaskRequest(BaseModel):
    records: List[RecordItem]

class CountRecordSchema(BaseModel):
    task_id: int
    vehicle_class: str
    video_time: float

class SaveCountsPayload(BaseModel):
    records: List[CountRecordSchema]

# ==========================================
# WORKSPACE DO FREELANCER
# ==========================================
@router.get("/freelancer/workspace", response_class=HTMLResponse)
def workspace_page(request: Request):
    return templates.TemplateResponse(request=request, name="workspace.html")

@router.get("/api/freelancer/workspace/{user_id}")
def get_workspace_data(user_id: int, db: Session = Depends(get_db)):
    # Certifique-se de que Project está importado no topo do seu arquivo
    from models import User, WorkPackage, MovementTask, VideoSlice, Video, Project, SliceStatus
    
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
        pendentes = total_tasks - completed_tasks
        
        # Se não tem nada pendente neste pacote, não manda pro Frontend
        if pendentes == 0:
            continue
            
        total_tasks_global += pendentes
        agrupamento_videos = {}
        
        for t in tarefas:
            if t.status == SliceStatus.completed: 
                continue 
            
            # Usando as relações (hasattr) do SQLAlchemy para evitar bater no banco 100x
            fatia = t.slice if hasattr(t, 'slice') and t.slice else db.query(VideoSlice).filter(VideoSlice.id == t.slice_id).first()
            if not fatia: continue
            
            video = fatia.video if hasattr(fatia, 'video') and fatia.video else db.query(Video).filter(Video.id == fatia.video_id).first()
            if not video: continue

            # Puxa o nome real do Projeto
            projeto = video.project if hasattr(video, 'project') and video.project else db.query(Project).filter(Project.id == video.project_id).first()
            nome_projeto = projeto.name if projeto else f"Projeto #{video.project_id}"
            
            v_id = video.id
            if v_id not in agrupamento_videos:
                agrupamento_videos[v_id] = {
                    "video_id": v_id, 
                    "filename": video.original_filename, 
                    "project_name": nome_projeto, # 🔴 Nome Real Aqui
                    "slices": {}
                }
            
            s_id = fatia.id
            if s_id not in agrupamento_videos[v_id]["slices"]:
                agrupamento_videos[v_id]["slices"][s_id] = {
                    "slice_id": s_id, 
                    "name": fatia.name, 
                    "tasks": []
                }
            
            mov_nome = t.movement.name if hasattr(t, 'movement') and t.movement else "Movimento"
            agrupamento_videos[v_id]["slices"][s_id]["tasks"].append({
                "id": t.id, 
                "movement_name": mov_nome
            })
        
        for v in agrupamento_videos.values():
            v["slices"] = list(v["slices"].values())
            
        # Puxa o nome real do Projeto pro Pacote também
        pkg_proj = db.query(Project).filter(Project.id == p.project_id).first()
        pkg_nome_projeto = pkg_proj.name if pkg_proj else f"Projeto #{p.project_id}"
            
        packages_data.append({
            "package_id": p.id, 
            "package_name": p.name, 
            "project_name": pkg_nome_projeto, # 🔴 Nome Real Aqui
            "progress": f"{completed_tasks}/{total_tasks} Movimentos Concluídos", 
            "videos": list(agrupamento_videos.values())
        })
    
    return {
        "freelancer_name": freela.name, 
        "total_tasks": total_tasks_global,
        "total_packages": len(packages_data), 
        "packages": packages_data
    }

# ==========================================
# REPRODUTOR E CONTAGEM
# ==========================================
@router.get("/freelancer/workspace/counter/{slice_id}", response_class=HTMLResponse)
def counter_page(request: Request, slice_id: int):
    return templates.TemplateResponse(request=request, name="counter.html", context={"slice_id": slice_id})

@router.get("/api/workspace/slice/{slice_id}/data")
def get_slice_counter_data(slice_id: int, user_id: int, review: str = "false", task_id: Optional[int] = None, db: Session = Depends(get_db)):
    fatia = db.query(VideoSlice).filter(VideoSlice.id == slice_id).first()
    if not fatia: raise HTTPException(status_code=404, detail="Fatia não encontrada")
        
    if review.lower() == "true":
        query = db.query(MovementTask).filter(MovementTask.slice_id == slice_id, MovementTask.assigned_to == user_id)
        if task_id: query = query.filter(MovementTask.id == task_id)
        tarefas = query.all()
    else:
        tarefas = db.query(MovementTask).filter(MovementTask.slice_id == slice_id, MovementTask.assigned_to == user_id, MovementTask.status != SliceStatus.completed).all()
        
    tarefa_ids = [t.id for t in tarefas]
    registros_db = db.query(CountRecord).filter(CountRecord.task_id.in_(tarefa_ids)).all()
    registros_formatados = [{"task_id": r.task_id, "vehicle_class": r.vehicle_class, "video_time": r.video_time} for r in registros_db]

    def limpar_nome(nome): return re.sub(r'[\\/*?:"<>|]', "", nome).strip()
        
    cliente = fatia.video.project.client.name if fatia.video.project and fatia.video.project.client else "Cliente Padrão"
    projeto = fatia.video.project.name if fatia.video.project else "Projeto Padrão"
    url_video = f"/static/videos/{limpar_nome(cliente)}/{limpar_nome(projeto)}/{fatia.video.original_filename}"
    
    zonas_do_projeto = {}
    if fatia.video.project and hasattr(fatia.video.project, 'zones'):
        for z in fatia.video.project.zones:
            zonas_do_projeto[z.name.strip()] = z.geometry

    tasks_data = []
    for t in tarefas:
        task_info = {"id": t.id, "movement_name": t.movement.name if t.movement else "Desconhecido", "origin_zone": None, "destination_zone": None}
        if t.movement and t.movement.name:
            partes = t.movement.name.split(" ➔ ") if " ➔ " in t.movement.name else t.movement.name.split(" -> ")
            if len(partes) == 2:
                n_origem, n_destino = partes[0].strip(), partes[1].strip()
                if n_origem in zonas_do_projeto: task_info["origin_zone"] = {"name": n_origem, "geometry": zonas_do_projeto[n_origem]}
                if n_destino in zonas_do_projeto: task_info["destination_zone"] = {"name": n_destino, "geometry": zonas_do_projeto[n_destino]}
        tasks_data.append(task_info)
    
    return {"video_url": url_video, "slice_name": fatia.name, "project_name": f"Projeto #{fatia.video.project_id}", "tasks": tasks_data, "existing_records": registros_formatados}

@router.post("/api/workspace/slice/{slice_id}/save")
def save_counts(slice_id: int, payload: SaveCountsPayload, db: Session = Depends(get_db)):
    for record in payload.records:
        db.add(CountRecord(task_id=record.task_id, vehicle_class=record.vehicle_class, video_time=record.video_time))
    task_ids = set([r.task_id for r in payload.records])
    for tid in task_ids:
        task = db.query(MovementTask).filter(MovementTask.id == tid).first()
        if task: task.status = SliceStatus.completed
    db.commit()
    return {"message": "Contagens salvas com sucesso!"}

@router.post("/api/tasks/{task_id}/complete")
def complete_task(task_id: int, payload: CompleteTaskRequest, db: Session = Depends(get_db)):
    task = db.query(MovementTask).filter(MovementTask.id == task_id).first()
    if not task: raise HTTPException(status_code=404, detail="Tarefa não encontrada")
        
    task.status = SliceStatus.completed
    db.query(CountRecord).filter(CountRecord.task_id == task_id).delete()

    db.add_all([CountRecord(task_id=task_id, vehicle_class=r.vehicle_class, video_time=r.video_time) for r in payload.records])
    db.commit()

    if task.work_package_id:
        todas_tarefas_pacote = db.query(MovementTask).filter(MovementTask.work_package_id == task.work_package_id).all()
        if all(t.status == SliceStatus.completed for t in todas_tarefas_pacote):
            pacote = db.query(WorkPackage).filter(WorkPackage.id == task.work_package_id).first()
            if pacote:
                pacote.status = "completed"
                db.commit()

    return {"message": "Tarefa concluída e salva com sucesso!"}

@router.get("/api/workspace/{user_id}/history")
def get_user_history(user_id: int, db: Session = Depends(get_db)):
    tarefas_concluidas = db.query(MovementTask).filter(MovementTask.assigned_to == user_id, MovementTask.status == SliceStatus.completed).all()
    resultado = []
    for t in tarefas_concluidas:
        total_veiculos = db.query(func.count(CountRecord.id)).filter(CountRecord.task_id == t.id).scalar() or 0
        fatia = db.query(VideoSlice).filter(VideoSlice.id == t.slice_id).first()
        video = fatia.video if fatia else None
        projeto = video.project if video else None
        
        resultado.append({
            "task_id": t.id,
            "video_filename": video.original_filename if video else "Desconhecido",
            "project": f"Projeto #{projeto.id}" if projeto else "Avulso",
            "movement": t.movement.name if hasattr(t, 'movement') and t.movement else "Movimento",
            "slice_name": fatia.name if fatia else "Desconhecida",
            "total": total_veiculos,
            "slice_id": t.slice_id
        })
    return resultado[::-1]