import os
import time
import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

API_URL = "http://localhost:8000/videos/staged"
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
ROOT_FOLDER_ID = "10Gw9FrTnl6BSQ1C5hW4Xq-NQiU9ilfwd" 

def authenticate_gdrive():
    creds = None
    token_path = os.path.join(os.path.dirname(__file__), '..', 'token.json')
    creds_path = os.path.join(os.path.dirname(__file__), '..', 'credentials.json')

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

def get_folder_name(service, folder_id):
    try:
        folder = service.files().get(fileId=folder_id, fields="name, parents").execute()
        parent_id = folder.get('parents', [None])[0]
        return folder.get('name'), parent_id
    except:
        return "Desconhecido", None

def scan_drive_and_sync():
    print("⏳ Conectando ao Google Drive...")
    service = authenticate_gdrive()
    
    # Robô burro: sempre pede os últimos 10 vídeos, sem memória.
    query = f"mimeType contains 'video/mp4' and trashed = false"
    print("✅ Conectado! Buscando os 10 vídeos mais recentes...")

    results = service.files().list(
        q=query,
        pageSize=10,
        fields="files(id, name, parents, webViewLink)",
        orderBy="createdTime desc"
    ).execute()

    videos = results.get('files', [])

    if not videos:
        print("Nenhum vídeo encontrado.")
        return

    for video in videos:
        filename = video['name']
        parent_id = video.get('parents', [None])[0]
        if not parent_id: continue

        project_name, grand_parent_id = get_folder_name(service, parent_id)
        client_name, great_grand_parent_id = get_folder_name(service, grand_parent_id)

        if great_grand_parent_id != ROOT_FOLDER_ID: continue 

        payload = {
            "client_name": client_name,
            "project_name": project_name,
            "original_filename": filename,
            "location_name": filename.split("_")[1] if "_" in filename else "Local Desconhecido",
            "file_path": video.get('webViewLink', 'Link Indisponível') 
        }

        try:
            response = requests.post(API_URL, json=payload)
            if response.status_code == 201:
                print(f"✅ NOVO: {filename} cadastrado com sucesso!")
            elif response.status_code == 409:
                print(f"⏩ BARRADO: {filename} já existe no banco. Pulando.")
            else:
                print(f"⚠️ Erro: {response.text}")
        except requests.exceptions.ConnectionError:
            print("❌ Erro: O servidor FastAPI (app.py) não está rodando!")
            return

if __name__ == '__main__':
    print("🤖 Iniciando o Robô Idempotente...")
    try:
        while True:
            scan_drive_and_sync()
            print("\n💤 Descansando por 60 segundos...\n")
            time.sleep(60) 
    except KeyboardInterrupt:
        print("\n🛑 Robô desligado.")