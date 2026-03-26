import os
from datetime import datetime
import enum
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Enum, Boolean, DateTime, Time
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()

# ==========================================
# 1. ENUMS (Tipos Restritos)
# ==========================================
class UserRole(enum.Enum):
    admin = "admin"
    data_operator = "data_operator"
    freelancer = "freelancer"

class VideoStatus(enum.Enum):
    staged = "staged"
    processing = "processing"
    review = "review"
    completed = "completed"

class TaskStatus(enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"

# ==========================================
# 2. HIERARQUIA DE NEGÓCIOS (NOVO)
# ==========================================
class Client(Base):
    """Clientes da ContaVias (Empresas, Prefeituras, Concessionárias)"""
    __tablename__ = 'clients'
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    company_name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Um cliente possui vários projetos
    projects = relationship("Project", back_populates="client", cascade="all, delete-orphan")

class Project(Base):
    """Projetos específicos de um Cliente (Ex: 'Estudo de Tráfego - Marginal Tietê')"""
    __tablename__ = 'projects'
    
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="projects")
    # Um projeto possui vários vídeos
    videos = relationship("Video", back_populates="project", cascade="all, delete-orphan")

# ==========================================
# 3. TABELAS DE DOMÍNIO
# ==========================================
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.freelancer, nullable=False)
    is_active = Column(Boolean, default=True)

    tasks = relationship("Task", back_populates="freelancer")

class Video(Base):
    __tablename__ = 'videos'
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False) # LIGAÇÃO COM O PROJETO
    
    original_filename = Column(String, nullable=False)
    location_name = Column(String, nullable=False)
    upload_date = Column(DateTime, default=datetime.utcnow)
    total_duration_seconds = Column(Integer, nullable=True)
    status = Column(Enum(VideoStatus), default=VideoStatus.staged, nullable=False)
    ai_model_id = Column(String, nullable=True)
    file_path = Column(String, nullable=False)
    
    project = relationship("Project", back_populates="videos")
    slices = relationship("VirtualSlice", back_populates="video", cascade="all, delete-orphan")
    movements = relationship("Movement", back_populates="video", cascade="all, delete-orphan")

class VirtualSlice(Base):
    __tablename__ = 'virtual_slices'
    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey('videos.id'), nullable=False)
    name = Column(String, nullable=False)
    start_time_seconds = Column(Integer, nullable=False)
    end_time_seconds = Column(Integer, nullable=False)
    
    video = relationship("Video", back_populates="slices")
    tasks = relationship("Task", back_populates="virtual_slice")

class Movement(Base):
    __tablename__ = 'movements'
    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey('videos.id'), nullable=False)
    name = Column(String, nullable=False)
    geometry_json = Column(String, nullable=True)
    
    video = relationship("Video", back_populates="movements")
    allocations = relationship("TaskAllocation", back_populates="movement")

class Category(Base):
    __tablename__ = 'categories'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)
    
    allocations = relationship("TaskAllocation", back_populates="category")

# ==========================================
# 4. O MOTOR DE ALOCAÇÃO
# ==========================================
class Task(Base):
    __tablename__ = 'tasks'
    
    id = Column(Integer, primary_key=True, index=True)
    freelancer_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    virtual_slice_id = Column(Integer, ForeignKey('virtual_slices.id'), nullable=False)
    
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    
    status = Column(Enum(TaskStatus), default=TaskStatus.pending, nullable=False)
    instructions = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    freelancer = relationship("User", back_populates="tasks")
    virtual_slice = relationship("VirtualSlice", back_populates="tasks")
    allocations = relationship("TaskAllocation", back_populates="task", cascade="all, delete-orphan")

class TaskAllocation(Base):
    __tablename__ = 'task_allocations'
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey('tasks.id'), nullable=False)
    movement_id = Column(Integer, ForeignKey('movements.id'), nullable=False)
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=False)
    
    task = relationship("Task", back_populates="allocations")
    movement = relationship("Movement", back_populates="allocations")
    category = relationship("Category", back_populates="allocations")

# ==========================================
# 5. FUNÇÃO DE INICIALIZAÇÃO
# ==========================================
def init_db(db_path="sqlite:///db/contavias.sqlite3"):
    db_file = db_path.replace("sqlite:///", "")
    os.makedirs(os.path.dirname(db_file), exist_ok=True)
    
    engine = create_engine(db_path, connect_args={"check_same_thread": False})
    
    # A forma correta e segura: o SQLAlchemy apaga as tabelas e recria, 
    # sem tentar deletar o arquivo físico bloqueado pelo Windows.
    print("Limpando tabelas antigas (se existirem)...")
    Base.metadata.drop_all(bind=engine)
    
    print("Criando novo schema do banco de dados...")
    Base.metadata.create_all(bind=engine)
    
    print(f"Banco de dados (V3) inicializado com sucesso em: {db_path}")
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)

if __name__ == "__main__":
    init_db()