from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# ==========================================
# 1. USERS (Freelas/Admins)
# ==========================================
class UserBase(BaseModel):
    name: str
    email: str
    role: str = "freelancer"

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    id: int
    class Config:
        from_attributes = True

# ==========================================
# 2. CLIENTS
# ==========================================
class ClientBase(BaseModel):
    name: str

class ClientCreate(ClientBase):
    pass

class ClientResponse(ClientBase):
    id: int
    class Config:
        from_attributes = True

# ==========================================
# 3. ZONES
# ==========================================
class ZoneBase(BaseModel):
    name: str
    geometry: List[List[float]]

class ZoneCreate(ZoneBase):
    pass

class ZoneResponse(ZoneBase):
    id: int
    project_id: int
    class Config:
        from_attributes = True

# ==========================================
# 4. PROJECTS
# ==========================================
class ProjectBase(BaseModel):
    name: str
    client_id: int

class ProjectCreate(ProjectBase):
    pass

class ProjectResponse(ProjectBase):
    id: int
    client: Optional[ClientResponse] = None
    zones: List[ZoneResponse] = []
    class Config:
        from_attributes = True

# ==========================================
# 5. VIDEO SLICES (Depende de User)
# ==========================================
class VideoSliceBase(BaseModel):
    name: str = "Vídeo Completo" 
    start_time: int
    end_time: int
    nominal_duration: int = 3600

class VideoSliceCreate(VideoSliceBase):
    pass

class VideoSliceResponse(VideoSliceBase):
    id: int
    video_id: int
    status: str
    assigned_to: Optional[int] = None
    freelancer: Optional[UserResponse] = None 
    class Config:
        from_attributes = True

# ==========================================
# 6. VIDEOS (Depende de Project e Slices)
# ==========================================
class VideoBase(BaseModel):
    original_filename: str
    location_name: Optional[str] = None
    file_path: str

class VideoCreate(VideoBase):
    client_name: str
    project_name: str

class VideoResponse(VideoBase):
    id: int
    status: str
    upload_date: datetime
    frame_urls: List[str] = []
    project: Optional[ProjectResponse] = None
    slices: List[VideoSliceResponse] = []
    
    class Config:
        from_attributes = True

class ProjectConfigCreate(BaseModel):
    zones: List[ZoneCreate]
    movements: List[str] # Lista com os nomes dos movimentos ativados pelo operador

class MovementResponse(BaseModel):
    id: int
    name: str
    class Config:
        from_attributes = True

# Opcional: Se quiser que a API já devolva os movimentos ao ler o Projeto
class ProjectResponse(ProjectBase):
    id: int
    client: Optional[ClientResponse] = None
    zones: List[ZoneResponse] = []
    movements: List[MovementResponse] = [] # NOVO
    class Config:
        from_attributes = True