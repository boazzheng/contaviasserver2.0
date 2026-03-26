from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Union

# ==========================================
# SCHEMAS BASE (ÉPICO 1)
# ==========================================

class ClientBase(BaseModel):
    name: str

class ClientResponse(ClientBase):
    id: int
    class Config:
        from_attributes = True

class ProjectBase(BaseModel):
    name: str
    client_id: int

class ProjectResponse(ProjectBase):
    id: int
    client: Optional[ClientResponse] = None
    class Config:
        from_attributes = True

# ==========================================
# NOVOS SCHEMAS DO ÉPICO 2 (Fatias e Zonas)
# ==========================================

class VideoSliceBase(BaseModel):
    start_time: str
    end_time: str
    status: Optional[str] = "pending"
    assigned_to: Optional[str] = None

class VideoSliceCreate(VideoSliceBase):
    pass

class VideoSliceResponse(VideoSliceBase):
    id: int
    video_id: int
    class Config:
        from_attributes = True

class ZoneBase(BaseModel):
    name: str
    # O formato que esperamos: [[x,y], [x,y], [x,y], ...]
    geometry: List[List[float]] 

class ZoneCreate(ZoneBase):
    pass

class ZoneResponse(ZoneBase):
    id: int
    video_id: int
    class Config:
        from_attributes = True

# ==========================================
# SCHEMA DO VÍDEO ATUALIZADO
# ==========================================

class VideoBase(BaseModel):
    project_id: Optional[int] = None
    original_filename: str
    location_name: str
    file_path: str
    status: Optional[str] = "staged"

class VideoCreate(BaseModel):
    client_name: str
    project_name: str
    original_filename: str
    location_name: str
    file_path: str

class VideoResponse(VideoBase):
    id: int
    upload_date: datetime
    frame_urls: List[str] = []
    project: Optional[ProjectResponse] = None
    slices: List[VideoSliceResponse] = []
    
    # Atualizado aqui: Devolvemos zonas!
    zones: List[ZoneResponse] = [] 
    
    class Config:
        from_attributes = True

class AutoSliceCreate(BaseModel):
    start_time: str
    end_time: str