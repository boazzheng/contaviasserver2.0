import os
import sys
import argparse
import cv2
import shutil

# --- Variáveis de Estado Globais ---
current_boxes = []
active_class = 3 
img_w, img_h = 0, 0

# Máquina de estados do Mouse
state = 'IDLE' # IDLE, DRAW, MOVE, RESIZE
drag_start = (0, 0)
active_pixel_box = [0, 0, 0, 0] # [x1, y1, x2, y2] da caixa em edição
active_box_cls = 0
resize_handle = None # 'TL', 'TR', 'BL', 'BR', 'T', 'B', 'L', 'R'
HIT_MARGIN = 8 # Área de captura do mouse (em pixels) para agarrar uma borda

CLASSES = {
    0: ('Auto', (255, 0, 0)),
    1: ('Moto', (0, 255, 0)),
    2: ('Onibus', (0, 255, 255)),
    3: ('Caminhao', (0, 0, 255))
}

def yolo_to_pixel(x_c, y_c, w, h, img_w, img_h):
    x1 = int((x_c - w / 2) * img_w)
    y1 = int((y_c - h / 2) * img_h)
    x2 = int((x_c + w / 2) * img_w)
    y2 = int((y_c + h / 2) * img_h)
    return [x1, y1, x2, y2]

def pixel_to_yolo(x1, y1, x2, y2, img_w, img_h):
    # Garante que as coordenadas estão na ordem certa mesmo se redimensionou invertido
    x_min, x_max = min(x1, x2), max(x1, x2)
    y_min, y_max = min(y1, y2), max(y1, y2)
    
    # Previne que a caixa saia da tela
    x_min, x_max = max(0, x_min), min(img_w, x_max)
    y_min, y_max = max(0, y_min), min(img_h, y_max)

    x_c = ((x_min + x_max) / 2) / img_w
    y_c = ((y_min + y_max) / 2) / img_h
    w = (x_max - x_min) / img_w
    h = (y_max - y_min) / img_h
    return x_c, y_c, w, h

def get_hit_target(x, y):
    """Detecta se o mouse clicou no centro, na borda ou fora de todas as caixas."""
    global current_boxes, img_w, img_h, HIT_MARGIN
    
    # Lê de trás para frente para pegar a caixa que está "por cima"
    for i in range(len(current_boxes)-1, -1, -1):
        cls_id, xc, yc, bw, bh = current_boxes[i]
        x1, y1, x2, y2 = yolo_to_pixel(xc, yc, bw, bh, img_w, img_h)
        
        # 1. Checa os cantos (Prioridade alta)
        if abs(x - x1) <= HIT_MARGIN and abs(y - y1) <= HIT_MARGIN: return i, 'TL'
        if abs(x - x2) <= HIT_MARGIN and abs(y - y1) <= HIT_MARGIN: return i, 'TR'
        if abs(x - x1) <= HIT_MARGIN and abs(y - y2) <= HIT_MARGIN: return i, 'BL'
        if abs(x - x2) <= HIT_MARGIN and abs(y - y2) <= HIT_MARGIN: return i, 'BR'
        
        # 2. Checa as arestas
        if x1 - HIT_MARGIN <= x <= x2 + HIT_MARGIN:
            if abs(y - y1) <= HIT_MARGIN: return i, 'T'
            if abs(y - y2) <= HIT_MARGIN: return i, 'B'
        if y1 - HIT_MARGIN <= y <= y2 + HIT_MARGIN:
            if abs(x - x1) <= HIT_MARGIN: return i, 'L'
            if abs(x - x2) <= HIT_MARGIN: return i, 'R'
            
        # 3. Checa o interior (Para mover)
        if x1 < x < x2 and y1 < y < y2:
            return i, 'C'
            
    return -1, None

def mouse_callback(event, x, y, flags, param):
    global state, drag_start, active_pixel_box, active_box_cls, resize_handle
    global current_boxes, active_class, img_w, img_h

    if event == cv2.EVENT_LBUTTONDOWN:
        box_idx, handle = get_hit_target(x, y)
        
        if handle is None:
            # Não clicou em nada: Cria nova caixa
            state = 'DRAW'
            active_box_cls = active_class
            active_pixel_box = [x, y, x, y]
        else:
            # Clicou numa caixa existente: Extrai ela da lista para edição
            cls_id, xc, yc, bw, bh = current_boxes.pop(box_idx)
            active_box_cls = cls_id
            active_pixel_box = yolo_to_pixel(xc, yc, bw, bh, img_w, img_h)
            drag_start = (x, y)
            
            if handle == 'C':
                state = 'MOVE'
            else:
                state = 'RESIZE'
                resize_handle = handle

    elif event == cv2.EVENT_MOUSEMOVE:
        if state == 'DRAW':
            active_pixel_box[2], active_pixel_box[3] = x, y
            
        elif state == 'MOVE':
            dx, dy = x - drag_start[0], y - drag_start[1]
            active_pixel_box[0] += dx; active_pixel_box[2] += dx
            active_pixel_box[1] += dy; active_pixel_box[3] += dy
            drag_start = (x, y) # Reseta o ponto de arrasto a cada frame
            
        elif state == 'RESIZE':
            if 'T' in resize_handle: active_pixel_box[1] = y
            if 'B' in resize_handle: active_pixel_box[3] = y
            if 'L' in resize_handle: active_pixel_box[0] = x
            if 'R' in resize_handle: active_pixel_box[2] = x

    elif event == cv2.EVENT_LBUTTONUP:
        if state in ['DRAW', 'MOVE', 'RESIZE']:
            x1, y1, x2, y2 = active_pixel_box
            # Só salva se a caixa tiver um tamanho mínimo (evita cliques falsos)
            if abs(x2 - x1) > 5 and abs(y2 - y1) > 5:
                yolo_box = pixel_to_yolo(x1, y1, x2, y2, img_w, img_h)
                current_boxes.append((active_box_cls, *yolo_box))
            state = 'IDLE'

    elif event == cv2.EVENT_RBUTTONDOWN:
        # Botão direito continua deletando a caixa clicada
        box_idx, handle = get_hit_target(x, y)
        if box_idx != -1:
            current_boxes.pop(box_idx)

def save_labels(lbl_path, boxes):
    if not boxes:
        if os.path.exists(lbl_path): os.remove(lbl_path)
        return
    with open(lbl_path, 'w') as f:
        for box in boxes:
            cls_id, x_c, y_c, w, h = box
            f.write(f"{cls_id} {x_c:.6f} {y_c:.6f} {w:.6f} {h:.6f}\n")

def run_curator(images_dir, labels_dir):
    global current_boxes, active_class, img_w, img_h, state, active_pixel_box, active_box_cls

    if not os.path.isdir(images_dir):
        print(f"Erro: Pasta não encontrada: {images_dir}"); sys.exit(1)
    
    os.makedirs(labels_dir, exist_ok=True)
    base_dir = os.path.dirname(images_dir.rstrip(os.sep))
    trash_img_dir = os.path.join(base_dir, "Lixeira", "images")
    trash_lbl_dir = os.path.join(base_dir, "Lixeira", "labels")
    os.makedirs(trash_img_dir, exist_ok=True); os.makedirs(trash_lbl_dir, exist_ok=True)

    image_files = sorted([f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg', '.png'))])
    if not image_files: print("Nenhuma imagem encontrada."); sys.exit(0)

    # =========================================================================
    # ALTERAÇÃO AQUI: WINDOW_NORMAL permite que a janela seja redimensionada.
    # O resizeWindow garante um tamanho inicial confortável.
    # =========================================================================
    cv2.namedWindow("Curador Profissional", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Curador Profissional", 1280, 720) 
    cv2.setMouseCallback("Curador Profissional", mouse_callback)

    print("\n=== Curador Profissional Iniciado ===")
    print("[ Mouse Esq. Fundo ] : Desenha nova caixa")
    print("[ Mouse Esq. Meio  ] : Arrastar caixa existente")
    print("[ Mouse Esq. Borda ] : Redimensionar caixa existente")
    print("[ Mouse Direito    ] : Apagar caixa")
    print("-------------------------------------")
    print("[ D ] / [ Espaço ]   : PRÓXIMA imagem")
    print("[ A ]                : Imagem ANTERIOR")
    print("[ X ]                : Mover imagem para a LIXEIRA")
    print("=====================================\n")

    i = 0
    while i < len(image_files):
        img_name = image_files[i]
        img_path = os.path.join(images_dir, img_name)
        base_name = os.path.splitext(img_name)[0]
        lbl_path = os.path.join(labels_dir, base_name + '.txt')

        img = cv2.imread(img_path)
        if img is None: i += 1; continue

        img_h, img_w, _ = img.shape
        current_boxes = []

        if os.path.exists(lbl_path):
            with open(lbl_path, 'r') as f:
                for line in f.readlines():
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        current_boxes.append((int(parts[0]), *map(float, parts[1:5])))

        while True:
            display_img = img.copy()

            # Desenha as caixas inativas
            for box in current_boxes:
                cls_id, xc, yc, w, h = box
                x1, y1, x2, y2 = yolo_to_pixel(xc, yc, w, h, img_w, img_h)
                name, color = CLASSES.get(cls_id, (f"ID_{cls_id}", (255, 255, 255)))
                cv2.rectangle(display_img, (x1, y1), (x2, y2), color, 2)
                cv2.putText(display_img, name, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            # Desenha a caixa ativa (em edição) com visual de destaque
            if state in ['DRAW', 'MOVE', 'RESIZE']:
                x1, y1, x2, y2 = active_pixel_box
                x_min, x_max = min(x1, x2), max(x1, x2)
                y_min, y_max = min(y1, y2), max(y1, y2)
                name, color = CLASSES.get(active_box_cls, ("Edicao", (255, 255, 255)))
                
                # Borda tracejada/destacada (amarelo) para mostrar que está agarrada
                cv2.rectangle(display_img, (x_min, y_min), (x_max, y_max), (0, 255, 255), 2)
                cv2.putText(display_img, name, (x_min, y_min - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

            # UI Header
            cv2.rectangle(display_img, (0, 0), (img_w, 60), (0, 0, 0), -1) 
            progress = f"IMG: {i+1}/{len(image_files)} | {img_name}"
            active_name, active_color = CLASSES.get(active_class)
            mode_text = f"Pincel Atual: [{active_class}] {active_name} | Modo: {state}"
            
            cv2.putText(display_img, progress, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            cv2.putText(display_img, mode_text, (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, active_color, 2)

            cv2.imshow("Curador Profissional", display_img)
            
            raw_key = cv2.waitKey(20)
            if raw_key == -1: continue
            key = raw_key & 0xFF

            if key in [ord('q'), 27]:
                save_labels(lbl_path, current_boxes); sys.exit(0)
            
            elif key in [ord('d'), 32]:
                save_labels(lbl_path, current_boxes)
                while cv2.waitKey(10) != -1: pass
                i += 1; break
                
            elif key == ord('a'):
                save_labels(lbl_path, current_boxes)
                while cv2.waitKey(10) != -1: pass
                i = max(0, i - 1); break
                
            elif key in [ord('x'), ord('X')]:
                try: shutil.move(img_path, os.path.join(trash_img_dir, img_name))
                except: pass
                if os.path.exists(lbl_path):
                    try: shutil.move(lbl_path, os.path.join(trash_lbl_dir, os.path.basename(lbl_path)))
                    except: pass
                image_files.pop(i)
                while cv2.waitKey(10) != -1: pass
                break 
                
            elif ord('0') <= key <= ord('3'):
                active_class = key - ord('0')

    cv2.destroyAllWindows()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", required=True)
    parser.add_argument("--labels", required=True)
    args = parser.parse_args()
    run_curator(args.images, args.labels)

if __name__ == "__main__":
    main()