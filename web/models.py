import enum
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, ForeignKey, Enum, DateTime, Text
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

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    original_filename = Column(String)
    location_name = Column(String, nullable=True)
    file_path = Column(String)
    status = Column(Enum(VideoStatus), default=VideoStatus.staged)
    upload_date = Column(DateTime, default=datetime.utcnow)

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

def init_db():
    Base.metadata.create_all(bind=engine)