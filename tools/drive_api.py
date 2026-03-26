import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def authenticate_gdrive():
    print("1. Iniciando função de autenticação...", flush=True)
    creds = None
    
    token_path = os.path.join(os.path.dirname(__file__), '..', 'token.json')
    creds_path = os.path.join(os.path.dirname(__file__), '..', 'credentials.json')

    print(f"2. Procurando token em: {token_path}", flush=True)
    if os.path.exists(token_path):
        print("   -> Token antigo encontrado. Tentando usar...", flush=True)
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("3. Token expirado. Tentando renovar...", flush=True)
            creds.refresh(Request())
        else:
            print(f"3. Nenhum token válido. Lendo arquivo de credenciais: {creds_path}", flush=True)
            if not os.path.exists(creds_path):
                print("❌ ERRO: O arquivo credentials.json NÃO foi encontrado na pasta raiz!", flush=True)
                return None
                
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            
            print("4. Iniciando servidor local na porta 8080 (Aguarde o link aparecer)...", flush=True)
            # Fixamos a porta 8080 e voltamos o open_browser para True para testar
            creds = flow.run_local_server(port=8080, open_browser=True)
            
        print("5. Salvando novo token...", flush=True)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    print("6. Autenticação finalizada com sucesso!", flush=True)
    return build('drive', 'v3', credentials=creds)

def testar_conexao():
    print("=== INÍCIO DO TESTE ===", flush=True)
    try:
        service = authenticate_gdrive()
        if not service:
            return
            
        print("✅ Conectado à API! Buscando arquivos...", flush=True)
        results = service.files().list(
            pageSize=5, 
            fields="nextPageToken, files(id, name, mimeType)",
            q="mimeType != 'application/vnd.google-apps.folder'"
        ).execute()
        
        items = results.get('files', [])

        if not items:
            print('Nenhum arquivo encontrado no Drive.')
        else:
            print("\nMeus últimos 5 arquivos:")
            for item in items:
                print(f"📄 {item['name']}")

    except Exception as e:
        print(f"\n❌ Erro durante a execução: {e}")

if __name__ == '__main__':
    testar_conexao()