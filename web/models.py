from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text
from sqlalchemy.orm import relationship
import enum
from datetime import datetime
from database import Base, engine
import json

# ==========================================
# TABELAS DO ÉPICO 1 (Estrutura Básica)
# ==========================================

class Client(Base):
    __tablename__ = "clients"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    
    projects = relationship("Project", back_populates="client")


class Project(Base):
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"))
    
    client = relationship("Client", back_populates="projects")
    videos = relationship("Video", back_populates="project")


class VideoStatus(str, enum.Enum):
    staged = "staged"             # Baixando
    ready = "ready"               # A Configurar (Download OK)
    configured = "configured"     # Configurado (Máscaras desenhadas)
    approved = "approved"         # Pronto (Liberado para a IA)
    processing = "processing"     # IA Trabalhando (A ser implementado)
    completed = "completed"       # IA Finalizou


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    original_filename = Column(String)
    location_name = Column(String)
    file_path = Column(String)
    status = Column(String, default=VideoStatus.staged)
    upload_date = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="videos")
    
    # Relações com as novas tabelas do Épico 2
    slices = relationship("VideoSlice", back_populates="video", cascade="all, delete-orphan")
    zones = relationship("Zone", back_populates="video", cascade="all, delete-orphan")


# ==========================================
# NOVAS TABELAS DO ÉPICO 2 (Fatiamento)
# ==========================================

class VideoSlice(Base):
    """Representa um pedaço de tempo do vídeo (ex: das 07:00 às 08:00)"""
    __tablename__ = "video_slices"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"))
    
    start_time = Column(String) 
    end_time = Column(String)   
    status = Column(String, default="pending") 
    assigned_to = Column(String, nullable=True) 

    video = relationship("Video", back_populates="slices")

class Zone(Base):
    __tablename__ = "video_zones"
    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"))
    name = Column(String)
    
    # A MÁGICA: Guardamos os pontos [[x1,y1], [x2,y2], ...] como TEXTO
    geometry_data = Column(Text) 

    video = relationship("Video", back_populates="zones")

    # Propriedades utilitárias para lidar com JSON (facilita o resto do código)
    @property
    def geometry(self):
        """Devolve os pontos como uma lista Python do JSON salvo."""
        return json.loads(self.geometry_data) if self.geometry_data else []

    @geometry.setter
    def geometry(self, points_list):
        """Salva a lista Python de pontos como JSON no banco."""
        self.geometry_data = json.dumps(points_list)

def init_db():
    """Cria todas as tabelas no banco de dados SQLite"""
    Base.metadata.create_all(bind=engine)