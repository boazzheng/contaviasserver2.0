import enum
import json
from datetime import datetime
from sqlalchemy import JSON, Column, Integer, String, ForeignKey, Enum, DateTime, Text, Float, Boolean
from sqlalchemy.orm import relationship

# Importe a Base e o engine do seu arquivo database.py
from database import Base, engine

# ==========================================
# ENUMS DE STATUS
# ==========================================
class VideoStatus(str, enum.Enum):
    staged = "staged"
    ready = "ready"
    configured = "configured"
    approved = "approved"
    processing = "processing"
    completed = "completed"

class SliceStatus(str, enum.Enum):
    pending = "pending"
    assigned = "assigned"
    counting = "counting"
    review = "review"
    completed = "completed"

# ==========================================
# TABELAS DO BANCO DE DADOS
# ==========================================
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    email = Column(String, unique=True, index=True)
    role = Column(String, default="freelancer") 
    
    # ATUALIZADO: O Freela agora é dono de Tarefas, não mais de Fatias inteiras
    tasks = relationship("MovementTask", back_populates="freelancer")

class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    
    projects = relationship("Project", back_populates="client")

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"))
    name = Column(String, index=True)
    
    client = relationship("Client", back_populates="projects")
    videos = relationship("Video", back_populates="project")
    zones = relationship("Zone", back_populates="project", cascade="all, delete-orphan")
    
    # RELAÇÃO COM MOVIMENTOS:
    movements = relationship("Movement", back_populates="project", cascade="all, delete-orphan")
    status = Column(String, default="processing")
    audit_selections = Column(JSON, default=dict)

class WorkPackage(Base):
    __tablename__ = 'work_packages'
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)  # Ex: "Local 1 - Câmera Norte" ou "Interseção A"
    project_id = Column(Integer, ForeignKey('projects.id'))
    freelancer_id = Column(Integer, ForeignKey('users.id'))
    status = Column(String, default="pending")  # pending, in_progress, completed
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relacionamentos
    project = relationship("Project")
    freelancer = relationship("User")
    
    # Um pacote tem várias micro-tarefas (movimentos de vídeos)
    micro_tasks = relationship("MovementTask", back_populates="work_package", cascade="all, delete-orphan")

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    original_filename = Column(String)
    location_name = Column(String, nullable=True)
    file_path = Column(String)
    status = Column(Enum(VideoStatus), default=VideoStatus.staged)
    upload_date = Column(DateTime, default=datetime.utcnow)

    is_validation = Column(Boolean, default=False)  # Para diferenciar tarefas de contagem das de validação
    project = relationship("Project", back_populates="videos")
    slices = relationship("VideoSlice", back_populates="video", cascade="all, delete-orphan")

class VideoSlice(Base):
    __tablename__ = "video_slices"
    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"))
    
    name = Column(String) 
    start_time = Column(Integer) 
    end_time = Column(Integer)   
    nominal_duration = Column(Integer, default=3600) 
    
    # REMOVIDOS OS CAMPOS DE STATUS E ASSIGNED_TO DAQUI!
    
    video = relationship("Video", back_populates="slices")
    
    # NOVA RELAÇÃO: A fatia agora é dona de várias Tarefas de Movimento
    tasks = relationship("MovementTask", back_populates="video_slice", cascade="all, delete-orphan")

class Zone(Base):
    __tablename__ = "project_zones"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    name = Column(String)
    geometry_data = Column(Text) 

    project = relationship("Project", back_populates="zones")

    @property
    def geometry(self):
        return json.loads(self.geometry_data) if self.geometry_data else []

    @geometry.setter
    def geometry(self, points_list):
        self.geometry_data = json.dumps(points_list)

# NOVA TABELA: MOVIMENTOS
class Movement(Base):
    __tablename__ = "project_movements"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    name = Column(String) 

    # O "aperto de mão" de volta para o Project:
    project = relationship("Project", back_populates="movements")

class MovementTask(Base):
    __tablename__ = "movement_tasks"
    id = Column(Integer, primary_key=True, index=True)
    slice_id = Column(Integer, ForeignKey("video_slices.id"))
    movement_id = Column(Integer, ForeignKey("project_movements.id"))
    
    status = Column(Enum(SliceStatus), default=SliceStatus.pending)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    video_slice = relationship("VideoSlice", back_populates="tasks")
    movement = relationship("Movement")
    freelancer = relationship("User", back_populates="tasks")
    work_package_id = Column(Integer, ForeignKey('work_packages.id'), nullable=True)
    work_package = relationship("WorkPackage", back_populates="micro_tasks")
    
class CountRecord(Base):
    __tablename__ = "count_records"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("movement_tasks.id", ondelete="CASCADE"))
    vehicle_class = Column(String)  # ex: "carro", "moto", "onibus", "caminhao"
    video_time = Column(Float)      # O segundo exato do vídeo (ex: 125.4)
    is_approved = Column(Boolean, default=False)
    # Relação reversa (opcional, mas boa prática)
    task = relationship("MovementTask", backref="records")

class ConsolidatedReport(Base):
    __tablename__ = "consolidated_reports"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    movement_name = Column(String)
    interval = Column(String)
    category = Column(String)
    count = Column(Integer, default=0)
    source = Column(String) # Guarda se veio do "H" ou "IA" para referência futura

    project = relationship("Project")

def init_db():
    Base.metadata.create_all(bind=engine)