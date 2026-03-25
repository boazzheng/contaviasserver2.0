import os
import sys
import argparse
import math
import cv2

try:
    from ultralytics import YOLO
except ImportError:
    print("Erro crítico: O pacote 'ultralytics' não está instalado.")
    sys.exit(1)

# Mapeamento: Carro(2)->0, Moto(3)->1, Ônibus(5)->2, Caminhão(7)->3
COCO_TO_BASE = {2: 0, 3: 1, 5: 2, 7: 3}

# Classes alvo para extração do melhor frame (5 = Ônibus, 7 = Caminhão)
TARGET_CLASSES_FOR_EXPORT = [5, 7]

def process_video(video_path, model, images_dir, labels_dir, conf_thresh):
    """Processa um vídeo, rastreando veículos e exportando os melhores frames de ônibus e caminhões."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Erro ao abrir o vídeo (ignorando): {video_path}")
        return

    w_img = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h_img = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    center_img_x, center_img_y = w_img / 2, h_img / 2

    video_name = os.path.splitext(os.path.basename(video_path))[0]
    best_tracks = {}
    
    print(f"\nProcessando: {video_name}...")

    results = model.track(
        source=video_path, 
        stream=True, 
        classes=list(COCO_TO_BASE.keys()), 
        conf=conf_thresh, 
        tracker="botsort.yaml", 
        verbose=False,
        persist=True
    )

    extracted_count = {'bus': 0, 'truck': 0}

    for r in results:
        if r.boxes is None or r.boxes.id is None:
            continue

        frame = r.orig_img
        targets_in_frame = []
        all_boxes_in_frame = []

        for box in r.boxes:
            track_id = int(box.id[0].item())
            coco_cls = int(box.cls[0].item())
            x_c, y_c, w, h = box.xywhn[0].tolist()
            
            # Anota todos os veículos mapeados
            if coco_cls in COCO_TO_BASE:
                mapped_cls = COCO_TO_BASE[coco_cls]
                all_boxes_in_frame.append(f"{mapped_cls} {x_c:.6f} {y_c:.6f} {w:.6f} {h:.6f}")

            # Se for Ônibus ou Caminhão, adiciona à lista de avaliação de melhor frame
            if coco_cls in TARGET_CLASSES_FOR_EXPORT:
                targets_in_frame.append({'id': track_id, 'cls': coco_cls, 'x_c': x_c, 'y_c': y_c, 'w': w, 'h': h})

        for target in targets_in_frame:
            margin = 0.05
            if (target['x_c'] - target['w']/2) < margin or (target['x_c'] + target['w']/2) > (1.0 - margin) or \
               (target['y_c'] - target['h']/2) < margin or (target['y_c'] + target['h']/2) > (1.0 - margin):
                continue

            area = target['w'] * target['h']
            pixel_x_c, pixel_y_c = target['x_c'] * w_img, target['y_c'] * h_img
            dist_to_center = math.hypot(pixel_x_c - center_img_x, pixel_y_c - center_img_y)
            score = area / (dist_to_center + 1)

            t_id = target['id']
            
            if t_id not in best_tracks or score > best_tracks[t_id]:
                # Se for um ID novo, contabiliza para o print final
                if t_id not in best_tracks:
                    if target['cls'] == 5: extracted_count['bus'] += 1
                    elif target['cls'] == 7: extracted_count['truck'] += 1

                best_tracks[t_id] = score
                
                # Define o prefixo dinâmico no nome do arquivo
                prefix = "bus" if target['cls'] == 5 else "truck"
                base_filename = f"{video_name}_{prefix}_{t_id}"
                
                img_path = os.path.join(images_dir, f"{base_filename}.jpg")
                txt_path = os.path.join(labels_dir, f"{base_filename}.txt")

                cv2.imwrite(img_path, frame)
                
                with open(txt_path, 'w') as f:
                    f.write('\n'.join(all_boxes_in_frame) + '\n')

    cap.release()
    print(f"-> Extraídos de '{video_name}': {extracted_count['bus']} ônibus e {extracted_count['truck']} caminhões.")

def main():
    parser = argparse.ArgumentParser(description="Extrai frames e anota todos os veículos recursivamente.")
    parser.add_argument("--input", type=str, required=True, help="Pasta raiz contendo os vídeos")
    parser.add_argument("--output", type=str, default="./dataset_completo", help="Pasta de saída do dataset")
    parser.add_argument("--model", type=str, default="yolo11x.pt", help="Caminho do modelo YOLO")
    parser.add_argument("--conf", type=float, default=0.25, help="Confiança mínima")
    
    args = parser.parse_args()

    if not os.path.isdir(args.input):
        print(f"Erro: O diretório de entrada não existe: {args.input}")
        sys.exit(1)

    images_base_dir = os.path.join(args.output, "images")
    labels_base_dir = os.path.join(args.output, "labels")

    print(f"Carregando modelo: {args.model}...")
    try:
        model = YOLO(args.model)
    except Exception as e:
        print(f"Erro ao carregar o modelo: {e}")
        sys.exit(1)

    valid_exts = ('.mp4', '.avi', '.mkv', '.mov')
    video_files = []
    for root, dirs, files in os.walk(args.input):
        for file in files:
            if file.lower().endswith(valid_exts):
                video_files.append(os.path.join(root, file))

    if not video_files:
        print(f"Nenhum vídeo suportado encontrado em: {args.input}")
        sys.exit(0)

    print(f"{len(video_files)} vídeos encontrados. Iniciando processamento em lote...")
    
    for video_path in video_files:
        # --- MUDANÇA PRINCIPAL AQUI ---
        # 1. Pega a pasta onde o vídeo está e calcula o caminho relativo à pasta raiz de input
        video_dir = os.path.dirname(video_path)
        rel_dir = os.path.relpath(video_dir, args.input)
        
        # Se o vídeo estiver na raiz do input, rel_dir será '.', então lidamos com isso
        if rel_dir == '.':
            rel_dir = ''
            
        # 2. Constrói as subpastas espelhando o input dentro do output
        current_images_dir = os.path.join(images_base_dir, rel_dir)
        current_labels_dir = os.path.join(labels_base_dir, rel_dir)
        
        # 3. Cria as pastas se não existirem
        os.makedirs(current_images_dir, exist_ok=True)
        os.makedirs(current_labels_dir, exist_ok=True)

        # 4. Passa o diretório de destino correto para o processador
        process_video(video_path, model, current_images_dir, current_labels_dir, args.conf)

    print(f"\nProcessamento em lote concluído! Dataset salvo em: {args.output}")

if __name__ == "__main__":
    main()


# python extract_all_vehicles.py --input /mnt/dados/videos --output /mnt/dados/dataset_completo --model yolo11x.pt

# Procedimento geral para treinamento DNIT
# 1. Extrair os melhores frames de ônibus e caminhões dos vídeos usando este script.
# 2. A extração dos frames é imperfeito, então é necessário revisar o dataset para remover imagens irrelevantes manualmente.
# 3. Sincronizar as pastas de labels e imagens usando sync_labels.py.
# 4. Curar o dataset usando visualize_dataset.py, removendo imagens irrelevantes e corrigindo anotações.