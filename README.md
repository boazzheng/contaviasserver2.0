# ContaVias Server 2.0

Módulo de automação e processamento de vídeos de tráfego para classificação veicular padrão e DNIT (Departamento Nacional de Infraestrutura de Transportes). Este repositório contém os scripts de inferência em lote, extração de frames, curadoria de dataset e fine-tuning usando YOLOv11.

## Estrutura do Projeto

* **core/**: Scripts principais da aplicação em produção (gerenciamento de processos e zonas).
* **configs/**: Arquivos YAML de hiperparâmetros (tracker, validação).
* **tools/dnit_training/**: Pipeline de preparação de dados e treinamento do modelo DNIT.
* **data/**: (Ignorado pelo Git) Diretório local para vídeos brutos e datasets extraídos.
* **weights/**: (Ignorado pelo Git) Pesos dos modelos `.pt`.

## Instalação e Configuração (Setup Local)

Abra o terminal na raiz do projeto e crie um ambiente virtual isolado para não conflitar com outros projetos Python no seu sistema.

1. Crie o ambiente virtual:
python -m venv .venv

2. Ative o ambiente virtual:
# No Windows:
.venv\Scripts\activate
# No Linux/WSL:
source .venv/bin/activate

3. Instale as dependências:
pip install -r requirements.txt

## Fluxo de Trabalho: Pipeline de Treinamento DNIT

Abaixo está a ordem de execução dos scripts localizados em `tools/dnit_training/` para gerar um novo dataset:

1. **Extração de Frames (Single-Pass)**: Rastreia veículos em múltiplos vídeos e exporta os melhores frames de caminhões e ônibus, mantendo a hierarquia de pastas.
python tools/dnit_training/0_extract_best_trucks.py --input data/videos_brutos --output data/dataset_dnit

2. **Curadoria Visual Avançada**: Interface OpenCV para desenhar, redimensionar, mover e deletar bounding boxes incorretos. Exclusões são enviadas para a pasta Lixeira com segurança.
python tools/dnit_training/2_visualize_dataset.py --images data/dataset_dnit/images --labels data/dataset_dnit/labels

3. **Treinamento (Fine-Tuning)**: Inicia o retreinamento do YOLO para as classes específicas do DNIT.
python tools/dnit_training/train.py --data configs/dnit.yaml --weights weights/yolo11x.pt --epochs 100