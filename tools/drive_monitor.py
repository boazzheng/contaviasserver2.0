import os
import time
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configurações
API_URL = "http://localhost:8000/videos/staged"
# Aponta para a pasta que criamos (ContaVias/dev/data/drive_sync)
WATCH_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "drive_sync"))

class VideoHandler(FileSystemEventHandler):
    def process_video(self, file_path):
        if not file_path.lower().endswith(".mp4"):
            return

        time.sleep(2) # Espera a cópia terminar
        
        # LÓGICA DE PASTAS: Extrai o Cliente e o Projeto do caminho do arquivo
        # Ex: "C:/.../drive_sync/Prefeitura/Av Paulista/video.mp4"
        rel_path = os.path.relpath(file_path, WATCH_DIR)
        parts = os.path.normpath(rel_path).split(os.sep)

        # Verifica se está na hierarquia correta (precisa ter no mínimo 3 partes)
        if len(parts) < 3:
            print(f"⚠️ Ignorado: '{rel_path}' não está na estrutura Cliente/Projeto/Video.mp4")
            return

        client_name = parts[0]
        project_name = parts[1]
        filename = parts[-1]

        print(f"\n🎬 Novo vídeo detectado!")
        print(f"🏢 Cliente: {client_name} | 📁 Projeto: {project_name} | 🎞️ Arquivo: {filename}")

        location = filename.split("_")[1] if "_" in filename else "Local Desconhecido"

        payload = {
            "client_name": client_name,
            "project_name": project_name,
            "original_filename": filename,
            "location_name": location,
            "file_path": file_path
        }

        try:
            print("⏳ Enviando para o ContaVias Server...")
            response = requests.post(API_URL, json=payload)
            
            if response.status_code == 201:
                print(f"✅ Sucesso! Sincronizado com o banco de dados.")
            else:
                print(f"❌ Erro na API: {response.text}")
        except Exception as e:
            print(f"❌ Erro de conexão com a API: {e}")

    # Quando um arquivo é colado/criado na pasta
    def on_created(self, event):
        if not event.is_directory:
            self.process_video(event.src_path)
            
    # Quando um arquivo é movido/renomeado para dentro da pasta
    def on_moved(self, event):
        if not event.is_directory:
            self.process_video(event.dest_path)

def start_monitor():
    os.makedirs(WATCH_DIR, exist_ok=True)
    print(f"👀 Robô iniciado. Vigiando a pasta: {WATCH_DIR}")
    print("Pressione Ctrl+C para parar.")
    
    event_handler = VideoHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_DIR, recursive=True)
    observer.start()
    
    try:
        while True:
            time.sleep(1) # Mantém o script rodando infinitamente
    except KeyboardInterrupt:
        observer.stop()
        print("\nRobô desligado.")
    observer.join()

if __name__ == "__main__":
    start_monitor()