from pydantic import BaseModel, ConfigDict
from datetime import datetime

# ==========================================
# SCHEMAS DE RELACIONAMENTO (Novos)
# ==========================================
class ClientResponse(BaseModel):
    name: str
    model_config = ConfigDict(from_attributes=True)

class ProjectResponse(BaseModel):
    name: str
    client: ClientResponse  # O Projeto carrega o Cliente com ele
    model_config = ConfigDict(from_attributes=True)

# ==========================================
# SCHEMAS PARA VÍDEOS (Atualizado)
# ==========================================
class VideoCreate(BaseModel):
    client_name: str     # <-- Adicionado
    project_name: str    # <-- Adicionado
    original_filename: str
    location_name: str
    file_path: str

class VideoResponse(BaseModel):
    id: int
    project_id: int
    original_filename: str
    location_name: str
    status: str
    upload_date: datetime
    
    # NOVA LINHA: O SQLAlchemy vai preencher isso automaticamente!
    project: ProjectResponse 
    
    model_config = ConfigDict(from_attributes=True)