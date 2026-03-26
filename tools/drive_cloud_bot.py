import os
import time
import requests
import cv2
import io
import re
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ==========================================
# CONFIGURAÇÕES DE PASTAS E API
# ==========================================
# 🔴 COLOQUE O ID DA SUA PASTA RAIZ DO CONTAVIAS AQUI
ROOT_FOLDER_ID = "19bg2e9q-H_76TZbuiL42MLIENoW5em4T" 

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
FRAMES_DIR = os.path.join(BASE_DIR, "web", "static", "frames")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(FRAMES_DIR, exist_ok=True)

API_URL = "http://localhost:8000/videos/staged"
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def authenticate_gdrive():
    creds = None
    token_path = os.path.join(BASE_DIR, 'token.json')
    creds_path = os.path.join(BASE_DIR, 'credentials.json')
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

def check_ancestry_and_get_names(service, parent_id, root_id):
    """
    Sobe a árvore de pastas do arquivo. 
    Retorna True se estiver dentro do ROOT_FOLDER_ID e devolve os nomes das pastas.
    """
    current_id = parent_id
    path_names = []
    depth = 0
    
    # Limita a 10 níveis de profundidade para não rodar infinitamente
    while current_id and depth < 10:
        if current_id == root_id:
            return True, path_names
            
        try:
            folder = service.files().get(fileId=current_id, fields="id, name, parents").execute()
            path_names.insert(0, folder.get('name'))
            parents = folder.get('parents')
            current_id = parents[0] if parents else None
            depth += 1
        except Exception:
            break
            
    return False, []

def limpar_nome_pasta(nome):
    """Remove caracteres que o Windows/Linux não aceitam em nomes de pastas."""
    return re.sub(r'[\\/*?:"<>|]', "", nome).strip()

def download_video(service, file_id, filename, cliente, projeto):
    # 1. Cria os nomes seguros para as pastas
    pasta_cliente = limpar_nome_pasta(cliente)
    pasta_projeto = limpar_nome_pasta(projeto)
    
    # 2. Monta o caminho completo: downloads / Nome do Cliente / Nome do Projeto
    caminho_destino = os.path.join(DOWNLOAD_DIR, pasta_cliente, pasta_projeto)
    
    # 3. Cria as pastas fisicamente no disco (se não existirem)
    os.makedirs(caminho_destino, exist_ok=True)
    
    # 4. Junta o caminho das pastas com o nome do vídeo
    filepath = os.path.join(caminho_destino, filename)
    
    if os.path.exists(filepath):
        print(f"⏩ Arquivo {filename} já existe em {caminho_destino}.")
        return filepath

    print(f"📥 Baixando {filename} para a pasta: {pasta_cliente}/{pasta_projeto}...")
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(filepath, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        print(f"Download {int(status.progress() * 100)}%.")
    return filepath

def extract_frames(video_path, video_id_db, cliente, projeto):
    print(f"📸 Extraindo frames de {video_path} de forma organizada...")
    cap = cv2.VideoCapture(video_path)
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0:
        print("⚠️ Erro: OpenCV não conseguiu ler o vídeo.")
        cap.release()
        return []

    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duracao_segundos = total_frames / fps

    # 1. Cria os nomes seguros para as pastas e monta o caminho completo
    pasta_cliente = limpar_nome_pasta(cliente)
    pasta_projeto = limpar_nome_pasta(projeto)
    
    # Nova estrutura: web/static/frames / Cliente / Projeto / ID_do_Video /
    caminho_frames_video = os.path.join(
        FRAMES_DIR, pasta_cliente, pasta_projeto, f"id_{video_id_db}"
    )
    
    # 2. Cria as pastas fisicamente no disco
    os.makedirs(caminho_frames_video, exist_ok=True)
    print(f"   📂 Pasta de frames criada: {caminho_frames_video}")
    
    frame_paths = []
    # 3. Loop de extração de 1 em 1 hora
    for i in range(0, int(duracao_segundos) + 1, 3600):
        cap.set(cv2.CAP_PROP_POS_MSEC, i * 1000)
        success, image = cap.read()
        
        if success:
            # Nome simplificado, pois a pasta já é única (ex: hour_0.jpg)
            frame_filename = f"hour_{i//3600}.jpg"
            save_path = os.path.join(caminho_frames_video, frame_filename)
            
            cv2.imwrite(save_path, image)
            frame_paths.append(save_path)
            print(f"   ✅ Frame salvo: {frame_filename}")
    
    cap.release()
    return frame_paths

def scan_and_process():
    service = authenticate_gdrive()
    
    # Mudamos de createdTime para modifiedTime para pegar arquivos renomeados!
    results = service.files().list(
        q="mimeType contains 'video/mp4' and trashed = false",
        fields="files(id, name, parents)",
        pageSize=10,
        orderBy="modifiedTime desc" 
    ).execute()
    
    arquivos = results.get('files', [])
    print(f"\n🔍 Varredura: O Google retornou os {len(arquivos)} vídeos mais recentemente modificados.")
    
    for file in arquivos:
        parents = file.get('parents')
        if not parents:
            continue
            
        # 1. O Escudo
        belongs_to_root, folder_path = check_ancestry_and_get_names(service, parents[0], ROOT_FOLDER_ID)
        
        if not belongs_to_root:
            print(f"🚫 Bloqueado pelo Escudo: '{file['name']}' (Fora da Raiz do ContaVias)")
            continue 
            
        # 2. Inteligência de Pastas
        cliente = folder_path[0] if len(folder_path) > 0 else "Cliente Padrão"
        projeto = folder_path[1] if len(folder_path) > 1 else "Projeto Padrão"
        
        payload = {
            "client_name": cliente,
            "project_name": projeto,
            "original_filename": file['name'],
            "location_name": file['name'].split(".")[0],
            "file_path": file['id']
        }
        
        try:
            res = requests.post(API_URL, json=payload)
            
            if res.status_code == 201:
                video_id = res.json()['id']
                print(f"✅ NOVO: '{file['name']}' (De: {cliente} > {projeto}) salvo no banco!")
                
                local_path = download_video(service, file['id'], file['name'], cliente, projeto)
                extract_frames(local_path, video_id, cliente, projeto)
                
                requests.patch(f"http://localhost:8000/videos/{video_id}/ready")
                print(f"🏁 Vídeo {video_id} liberado na interface web!")
            elif res.status_code == 409:
                print(f"⏩ Pulando: '{file['name']}' já está na fila de Staging.")
                
        except requests.exceptions.ConnectionError:
            print("❌ Erro: API offline. Ligue o servidor FastAPI.")
            return
        
if __name__ == '__main__':
    print("🤖 Robô OpenCV com Escudo de Pastas Iniciado!")
    while True:
        scan_and_process()
        print("💤 Aguardando 60 segundos...")
        time.sleep(60)