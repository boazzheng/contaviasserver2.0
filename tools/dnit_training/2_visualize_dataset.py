import os
import sys
import argparse
import cv2
import shutil
import json
import numpy as np

# ==============================================================================
# CONFIGURAÇÃO DE ROTEAMENTO RÁPIDO (CVS 2.0)
# ==============================================================================
# Top 12 Categorias alinhadas à anatomia da mão no teclado QWERTY.
MAPA_CLASSIFICACAO_ROTEAMENTO = {
    ord('y'): '2C',
    ord('u'): '3C',
    ord('i'): '3S3',
    ord('o'): '2CB',
    ord('h'): '4CD',
    ord('j'): '3I3',
    ord('k'): '1_2_1_3',
    ord('l'): '2S3 (1_1_3)',
    ord('n'): '2S2',
    ord('m'): '1_2_3_3',
    ord(','): '3D4 (1_2_2_2)',
    ord('.'): 'Cabine'
}
# ==============================================================================

# --- Variáveis de Estado Globais ---
current_boxes = []
active_class = 0 
img_w, img_h = 0, 0

state = 'IDLE' 
drag_start = (0, 0)
active_pixel_box = [0, 0, 0, 0] 
active_box_cls = 0
resize_handle = None 
HIT_MARGIN = 8 
current_mouse_pos = (0, 0)

CLASSES = {
    0: ('Carro', (255, 0, 0)),
    1: ('Moto', (0, 255, 0)),
    2: ('Onibus', (0, 255, 255)),
    3: ('Caminhao', (0, 0, 255))
}

def get_progress_file(labels_dir):
    return os.path.join(labels_dir, ".curator_progress.json")

def load_progress(labels_dir):
    prog_file = get_progress_file(labels_dir)
    if os.path.exists(prog_file):
        try:
            with open(prog_file, 'r') as f:
                data = json.load(f)
                return data.get("last_index", 0)
        except:
            return 0
    return 0

def save_progress(labels_dir, index):
    prog_file = get_progress_file(labels_dir)
    try:
        with open(prog_file, 'w') as f:
            json.dump({"last_index": index}, f)
    except Exception as e:
        print(f"Erro ao salvar progresso: {e}")

def yolo_to_pixel(x_c, y_c, w, h, img_w, img_h):
    x1 = int((x_c - w / 2) * img_w)
    y1 = int((y_c - h / 2) * img_h)
    x2 = int((x_c + w / 2) * img_w)
    y2 = int((y_c + h / 2) * img_h)
    return [x1, y1, x2, y2]

def pixel_to_yolo(x1, y1, x2, y2, img_w, img_h):
    x_min, x_max = min(x1, x2), max(x1, x2)
    y_min, y_max = min(y1, y2), max(y1, y2)
    x_min, x_max = max(0, x_min), min(img_w, x_max)
    y_min, y_max = max(0, y_min), min(img_h, y_max)
    x_c = ((x_min + x_max) / 2) / img_w
    y_c = ((y_min + y_max) / 2) / img_h
    w = (x_max - x_min) / img_w
    h = (y_max - y_min) / img_h
    return x_c, y_c, w, h

def get_hit_target(x, y):
    global current_boxes, img_w, img_h, HIT_MARGIN
    for i in range(len(current_boxes)-1, -1, -1):
        cls_id, xc, yc, bw, bh = current_boxes[i]
        x1, y1, x2, y2 = yolo_to_pixel(xc, yc, bw, bh, img_w, img_h)
        if abs(x - x1) <= HIT_MARGIN and abs(y - y1) <= HIT_MARGIN: return i, 'TL'
        if abs(x - x2) <= HIT_MARGIN and abs(y - y1) <= HIT_MARGIN: return i, 'TR'
        if abs(x - x1) <= HIT_MARGIN and abs(y - y2) <= HIT_MARGIN: return i, 'BL'
        if abs(x - x2) <= HIT_MARGIN and abs(y - y2) <= HIT_MARGIN: return i, 'BR'
        if x1 - HIT_MARGIN <= x <= x2 + HIT_MARGIN:
            if abs(y - y1) <= HIT_MARGIN: return i, 'T'
            if abs(y - y2) <= HIT_MARGIN: return i, 'B'
        if y1 - HIT_MARGIN <= y <= y2 + HIT_MARGIN:
            if abs(x - x1) <= HIT_MARGIN: return i, 'L'
            if abs(x - x2) <= HIT_MARGIN: return i, 'R'
        if x1 < x < x2 and y1 < y < y2: return i, 'C'
    return -1, None

def mouse_callback(event, x, y, flags, param):
    global state, drag_start, active_pixel_box, active_box_cls, resize_handle
    global current_boxes, active_class, img_w, img_h, current_mouse_pos
    current_mouse_pos = (x, y)
    if event == cv2.EVENT_LBUTTONDOWN:
        box_idx, handle = get_hit_target(x, y)
        if handle is None:
            state = 'DRAW'; active_box_cls = active_class; active_pixel_box = [x, y, x, y]
        else:
            cls_id, xc, yc, bw, bh = current_boxes.pop(box_idx)
            active_box_cls = cls_id; active_pixel_box = yolo_to_pixel(xc, yc, bw, bh, img_w, img_h)
            drag_start = (x, y)
            if handle == 'C': state = 'MOVE'
            else: state = 'RESIZE'; resize_handle = handle
    elif event == cv2.EVENT_MOUSEMOVE:
        if state == 'DRAW': active_pixel_box[2], active_pixel_box[3] = x, y
        elif state == 'MOVE':
            dx, dy = x - drag_start[0], y - drag_start[1]
            active_pixel_box[0] += dx; active_pixel_box[2] += dx
            active_pixel_box[1] += dy; active_pixel_box[3] += dy
            drag_start = (x, y)
        elif state == 'RESIZE':
            if 'T' in resize_handle: active_pixel_box[1] = y
            if 'B' in resize_handle: active_pixel_box[3] = y
            if 'L' in resize_handle: active_pixel_box[0] = x
            if 'R' in resize_handle: active_pixel_box[2] = x
    elif event == cv2.EVENT_LBUTTONUP:
        if state in ['DRAW', 'MOVE', 'RESIZE']:
            x1, y1, x2, y2 = active_pixel_box
            if abs(x2 - x1) > 5 and abs(y2 - y1) > 5:
                yolo_box = pixel_to_yolo(x1, y1, x2, y2, img_w, img_h)
                current_boxes.append((active_box_cls, *yolo_box))
            state = 'IDLE'
    elif event == cv2.EVENT_RBUTTONDOWN:
        box_idx, _ = get_hit_target(x, y)
        if box_idx != -1: current_boxes.pop(box_idx)

def save_labels(lbl_path, boxes):
    if not boxes:
        if os.path.exists(lbl_path): os.remove(lbl_path)
        return
    try:
        with open(lbl_path, 'w') as f:
            for box in boxes:
                cls_id, x_c, y_c, w, h = box
                f.write(f"{cls_id} {x_c:.6f} {y_c:.6f} {w:.6f} {h:.6f}\n")
    except Exception as e: print(f"Erro ao salvar label: {e}")

def run_curator(images_dir, labels_dir):
    global current_boxes, active_class, img_w, img_h, state, active_pixel_box, active_box_cls, current_mouse_pos

    if not os.path.isdir(images_dir): sys.exit(1)
    os.makedirs(labels_dir, exist_ok=True)
    
    base_dir = os.path.dirname(images_dir.rstrip(os.sep))
    trash_img_dir = os.path.join(base_dir, "Lixeira", "images")
    trash_lbl_dir = os.path.join(base_dir, "Lixeira", "labels")
    os.makedirs(trash_img_dir, exist_ok=True); os.makedirs(trash_lbl_dir, exist_ok=True)

    # Coleta apenas os arquivos de imagem soltos na raiz da pasta 'images'
    image_files = sorted([f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg', '.png'))])
    if not image_files: sys.exit(0)

    saved_idx = load_progress(labels_dir)
    i = 0
    if saved_idx > 0 and saved_idx < len(image_files):
        print(f"\n[SESSÃO] Detectado progresso na imagem {saved_idx + 1} ({image_files[saved_idx]})")
        resp = input("Deseja retomar de onde parou? (S/n): ").strip().lower()
        if resp != 'n':
            i = saved_idx

    # --- TELA SEPARADA: TECLADO VISUAL (GRID 3x4) ---
    legend_height = 350
    legend_width = 800
    legend_img = np.zeros((legend_height, legend_width, 3), dtype=np.uint8)
    
    cv2.putText(legend_img, "TECLADO DE ROTEAMENTO (GRID QWERTY)", (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.line(legend_img, (15, 50), (legend_width - 15, 50), (100, 100, 100), 1)
    
    grid_layout = [
        ['y', 'u', 'i', 'o'],
        ['h', 'j', 'k', 'l'],
        ['n', 'm', ',', '.']
    ]
    
    cell_w = 180
    cell_h = 70
    start_x = 20
    start_y = 70
    
    for row_idx, row in enumerate(grid_layout):
        for col_idx, key_char in enumerate(row):
            key_code = ord(key_char)
            cat_name = MAPA_CLASSIFICACAO_ROTEAMENTO.get(key_code, "N/A")
            
            x = start_x + col_idx * cell_w
            y = start_y + row_idx * cell_h
            
            cv2.rectangle(legend_img, (x, y), (x + cell_w - 10, y + cell_h - 10), (40, 40, 40), -1)
            cv2.rectangle(legend_img, (x, y), (x + cell_w - 10, y + cell_h - 10), (150, 150, 150), 1)
            
            display_char = key_char.upper()
            cv2.putText(legend_img, f"[{display_char}]", (x + 10, y + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.putText(legend_img, cat_name, (x + 10, y + 45), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
    cv2.putText(legend_img, "[ X ] -> Lixeira  |  [ D ] -> Prox  |  [ A ] -> Ant", (15, legend_height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1)

    cv2.imshow("Categorias - CVS2.0", legend_img)
    # ------------------------------------------------

    cv2.namedWindow("Curador CVS2.0", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Curador CVS2.0", 1280, 720) 
    cv2.setMouseCallback("Curador CVS2.0", mouse_callback)

    while i < len(image_files):
        img_name = image_files[i]
        img_path = os.path.join(images_dir, img_name)
        lbl_path = os.path.join(labels_dir, os.path.splitext(img_name)[0] + '.txt')

        img = cv2.imread(img_path)
        if img is None: i += 1; continue
        img_h, img_w, _ = img.shape
        current_boxes = []

        if os.path.exists(lbl_path):
            with open(lbl_path, 'r') as f:
                for line in f.readlines():
                    p = line.strip().split()
                    if len(p) >= 5: current_boxes.append((int(p[0]), *map(float, p[1:5])))

        while True:
            display_img = img.copy()
            for box in current_boxes:
                cid, xc, yc, w, h = box
                x1, y1, x2, y2 = yolo_to_pixel(xc, yc, w, h, img_w, img_h)
                name, color = CLASSES.get(cid, ("?", (255, 255, 255)))
                cv2.rectangle(display_img, (x1, y1), (x2, y2), color, 2)
                cv2.putText(display_img, name, (x1, y1 - 5), 0, 0.6, color, 2)

            if state in ['DRAW', 'MOVE', 'RESIZE']:
                x1, y1, x2, y2 = active_pixel_box
                cv2.rectangle(display_img, (min(x1,x2), min(y1,y2)), (max(x1,x2), max(y1,y2)), (0, 255, 255), 2)

            cv2.rectangle(display_img, (0, 0), (img_w, 60), (0, 0, 0), -1)
            cv2.putText(display_img, f"IMG: {i+1}/{len(image_files)} | {img_name}", (10, 25), 0, 0.6, (255,255,255), 1)
            
            cv2.imshow("Curador CVS2.0", display_img)
            
            raw_key = cv2.waitKey(20)
            if raw_key == -1: continue
            key = raw_key & 0xFF
            
            key_lower = ord(chr(key).lower()) if 0 <= key < 256 else key

            if key in [ord('q'), 27]:
                save_labels(lbl_path, current_boxes)
                save_progress(labels_dir, i) 
                sys.exit(0)
            elif key in [ord('d'), 32]:
                save_labels(lbl_path, current_boxes)
                i += 1
                save_progress(labels_dir, i) 
                break
            elif key == ord('a'): 
                save_labels(lbl_path, current_boxes)
                i = max(0, i - 1)
                save_progress(labels_dir, i)
                break
            elif key_lower == ord('x'): 
                try: shutil.move(img_path, os.path.join(trash_img_dir, img_name))
                except: pass
                if os.path.exists(lbl_path): shutil.move(lbl_path, os.path.join(trash_lbl_dir, os.path.basename(lbl_path)))
                image_files.pop(i)
                save_progress(labels_dir, i)
                break
            elif ord('0') <= key <= ord('3'):
                nk = key - ord('0')
                idx, _ = get_hit_target(current_mouse_pos[0], current_mouse_pos[1])
                if idx != -1: current_boxes[idx] = (nk, *current_boxes[idx][1:])
                else: active_class = nk
            elif key_lower in MAPA_CLASSIFICACAO_ROTEAMENTO:
                cat_name = MAPA_CLASSIFICACAO_ROTEAMENTO[key_lower]
                
                # --- LÓGICA ATUALIZADA (FLAT LABELS & CATEGORIZED IMAGES) ---
                # A pasta da categoria é criada DENTRO da própria pasta 'images'
                cat_img_dir = os.path.join(images_dir, cat_name)
                os.makedirs(cat_img_dir, exist_ok=True)
                
                new_img_path = os.path.join(cat_img_dir, img_name)
                
                # Move APENAS a imagem
                try: 
                    shutil.move(img_path, new_img_path)
                except Exception as e: 
                    print(f"Erro ao mover imagem para {cat_name}: {e}")
                    pass
                
                # Salva o label com as alterações atuais no mesmo local (pasta 'labels' raiz)
                save_labels(lbl_path, current_boxes)
                
                # Remove da fila de processamento visual
                image_files.pop(i)
                save_progress(labels_dir, i)
                break

    if i >= len(image_files) and os.path.exists(get_progress_file(labels_dir)):
        os.remove(get_progress_file(labels_dir))
    cv2.destroyAllWindows()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", required=True)
    parser.add_argument("--labels", required=True)
    args = parser.parse_args()
    run_curator(args.images, args.labels)

if __name__ == "__main__":
    main()