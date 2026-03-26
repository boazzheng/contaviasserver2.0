import os
import sys
from datetime import datetime

# Garante que o Python ache a pasta 'web' corretamente
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Correção: Importamos o init_db em vez do SessionLocal
from web.models import init_db, Client, Project, Video, VideoStatus

# Inicializa o banco e cria o SessionLocal aqui, igual fizemos no app.py
SessionLocal = init_db()

def seed_database():
    db = SessionLocal()
    
    try:
        # 1. Verifica se já tem dados para não duplicar
        if db.query(Client).first():
            print("O banco de dados já possui dados. Saindo do seed...")
            return

        print("Injetando dados de teste (Seed)...")

        # 2. Cria um Cliente de Teste
        cliente1 = Client(
            name="Prefeitura de São Paulo",
            company_name="CET - Companhia de Engenharia de Tráfego",
            email="contato@cetsp.gov.br"
        )
        db.add(cliente1)
        db.commit() 
        db.refresh(cliente1)

        # 3. Cria um Projeto vinculado a esse Cliente
        projeto1 = Project(
            client_id=cliente1.id,
            name="Estudo de Tráfego - Av. Paulista",
            description="Contagem classificada no cruzamento com a Rua Augusta"
        )
        db.add(projeto1)
        db.commit() 
        db.refresh(projeto1)

        # 4. Cria Vídeos que acabaram de sofrer upload (Fila de Staging - Épico 1)
        videos_iniciais = [
            Video(
                project_id=projeto1.id,
                original_filename="Paulista_Augusta_2026-03-25_07h00.mp4",
                location_name="Paulista_Augusta",
                status=VideoStatus.staged,
                file_path="/data/videos/Paulista_Augusta_2026-03-25_07h00.mp4"
            ),
            Video(
                project_id=projeto1.id,
                original_filename="Paulista_Augusta_2026-03-25_08h00.mp4",
                location_name="Paulista_Augusta",
                status=VideoStatus.staged, 
                file_path="/data/videos/Paulista_Augusta_2026-03-25_08h00.mp4"
            )
        ]
        
        db.add_all(videos_iniciais)
        db.commit()

        print("✅ Seed concluído! Cliente, Projeto e Vídeos na fila de Staging foram criados.")

    except Exception as e:
        print(f"❌ Erro ao popular o banco: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()