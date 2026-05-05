import os
import sys
import argparse
import cv2
import shutil
import json
import numpy as np
import copy # <-- Adicionado para copiar o estado das caixas (Undo)

# ==============================================================================
# CONFIGURAÇÃO DE ROTEAMENTO RÁPIDO (CVS 2.0)
# ==============================================================================
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

# --- Motor de Undo (Ctrl + Z) ---
history = []
current_img_index = 0

def push_history(action):
    global history
    # Evita salvar estados idênticos de marcação seguidos (ex: cliques falsos do mouse)
    if action['type'] == 'box' and history and history[-1]['type'] == 'box':
        if history[-1]['index'] == action['index'] and history[-1]['boxes'] == action['boxes']:
            return
    history.append(action)
    # Limita o histórico aos últimos 5 passos para poupar memória
    if len(history) > 5:
        history.pop(0)

# --- Variáveis do Grid Visual Ampliado ---
GRID_LAYOUT = [
    ['y', 'u', 'i', 'o'],
    ['h', 'j', 'k', 'l'],
    ['n', 'm', ',', '.']
]
CELL_W = 260
CELL_H = 180
START_X = 20
START_Y = 60
pending_routing_key = None 

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
        pass

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
    global current_boxes, active_class, img_w, img_h, current_mouse_pos, current_img_index
    current_mouse_pos = (x, y)
    
    if event == cv2.EVENT_LBUTTONDOWN:
        # Salva o estado ANTES de desenhar ou mexer
        push_history({'type': 'box', 'index': current_img_index, 'boxes': copy.deepcopy(current_boxes)})
        
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
        # Salva o estado ANTES de deletar
        push_history({'type': 'box', 'index': current_img_index, 'boxes': copy.deepcopy(current_boxes)})
        box_idx, _ = get_hit_target(x, y)
        if box_idx != -1: current_boxes.pop(box_idx)

def legend_mouse_callback(event, x, y, flags, param):
    global pending_routing_key
    if event == cv2.EVENT_LBUTTONDOWN:
        if START_X <= x <= START_X + 4 * CELL_W and START_Y <= y <= START_Y + 3 * CELL_H:
            col = (x - START_X) // CELL_W
            row = (y - START_Y) // CELL_H
            if 0 <= row < 3 and 0 <= col < 4:
                key_char = GRID_LAYOUT[row][col]
                pending_routing_key = ord(key_char)

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
    global pending_routing_key, current_img_index, history

    if not os.path.isdir(images_dir): sys.exit(1)
    os.makedirs(labels_dir, exist_ok=True)
    
    base_dir = os.path.dirname(images_dir.rstrip(os.sep))
    trash_img_dir = os.path.join(base_dir, "Lixeira", "images")
    trash_lbl_dir = os.path.join(base_dir, "Lixeira", "labels")
    os.makedirs(trash_img_dir, exist_ok=True); os.makedirs(trash_lbl_dir, exist_ok=True)

    ref_categorias_dir = os.path.join(base_dir, "_categorias")

    image_files = sorted([f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg', '.png'))])
    if not image_files: sys.exit(0)

    saved_idx = load_progress(labels_dir)
    i = 0
    if saved_idx > 0 and saved_idx < len(image_files):
        print(f"\n[SESSÃO] Detectado progresso na imagem {saved_idx + 1} ({image_files[saved_idx]})")
        resp = input("Deseja retomar de onde parou? (S/n): ").strip().lower()
        if resp != 'n':
            i = saved_idx

    # --- TELA SEPARADA: TECLADO VISUAL ---
    legend_height = START_Y + 3 * CELL_H + 50
    legend_width = START_X + 4 * CELL_W + 20
    legend_img = np.zeros((legend_height, legend_width, 3), dtype=np.uint8)
    
    cv2.putText(legend_img, "GABARITO DE ROTEAMENTO (GRID QWERTY) - CLIQUE OU USE O TECLADO", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.line(legend_img, (15, 45), (legend_width - 15, 45), (100, 100, 100), 1)
    
    for row_idx, row in enumerate(GRID_LAYOUT):
        for col_idx, key_char in enumerate(row):
            key_code = ord(key_char)
            cat_name = MAPA_CLASSIFICACAO_ROTEAMENTO.get(key_code, "N/A")
            
            x = START_X + col_idx * CELL_W
            y = START_Y + row_idx * CELL_H
            
            cv2.rectangle(legend_img, (x, y), (x + CELL_W - 10, y + CELL_H - 10), (30, 30, 30), -1)
            cv2.rectangle(legend_img, (x, y), (x + CELL_W - 10, y + CELL_H - 10), (100, 100, 100), 1)
            
            display_char = key_char.upper()
            cv2.putText(legend_img, f"[{display_char}] {cat_name}", (x + 10, y + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            
            thumb_w = CELL_W - 30
            thumb_h = CELL_H - 50
            thumb_x = x + 10
            thumb_y = y + 35
            
            img_loaded = False
            for ext in ['.jpg', '.png', '.jpeg']:
                ref_path = os.path.join(ref_categorias_dir, cat_name + ext)
                if os.path.exists(ref_path):
                    ref_img = cv2.imread(ref_path)
                    if ref_img is not None:
                        ref_img = cv2.resize(ref_img, (thumb_w, thumb_h))
                        legend_img[thumb_y:thumb_y+thumb_h, thumb_x:thumb_x+thumb_w] = ref_img
                        img_loaded = True
                        break
            
            if not img_loaded:
                cv2.putText(legend_img, "Imagem Ausente", (x + 50, y + 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 80, 80), 1)

    cv2.putText(legend_img, "[ X ] Lixeira  |  [ D ] Proxima  |  [ A ] Anterior  |  [ Ctrl+Z ] Desfazer", (15, legend_height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1)

    cv2.namedWindow("Gabarito - CVS2.0", cv2.WINDOW_NORMAL)
    cv2.imshow("Gabarito - CVS2.0", legend_img)
    cv2.setMouseCallback("Gabarito - CVS2.0", legend_mouse_callback)

    cv2.namedWindow("Curador CVS2.0", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Curador CVS2.0", 1280, 720) 
    cv2.setMouseCallback("Curador CVS2.0", mouse_callback)

    while i < len(image_files):
        current_img_index = i
        ui_message = ""
        ui_message_timer = 0
        
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

            # Feedback de UNDO
            if ui_message and ui_message_timer > 0:
                cv2.putText(display_img, ui_message, (img_w // 2 - 200, img_h // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 4)
                ui_message_timer -= 1

            mx, my = current_mouse_pos
            if 0 <= mx < img_w and 0 <= my < img_h and state == 'IDLE':
                act_name, act_color = CLASSES.get(active_class, ("?", (255,255,255)))
                cv2.putText(display_img, act_name, (mx + 15, my + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,0), 3)
                cv2.putText(display_img, act_name, (mx + 15, my + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, act_color, 2)

            cv2.rectangle(display_img, (0, 0), (img_w, 60), (0, 0, 0), -1)
            cv2.putText(display_img, f"IMG: {i+1}/{len(image_files)} | {img_name}", (10, 25), 0, 0.6, (255,255,255), 1)
            
            act_name_header, act_color_header = CLASSES.get(active_class, ("?", (255,255,255)))
            cv2.putText(display_img, f"Pincel [Numeros 0-3]: {act_name_header}", (10, 50), 0, 0.6, act_color_header, 2)
            
            cv2.imshow("Curador CVS2.0", display_img)
            
            raw_key = cv2.waitKey(20)
            key_lower = None
            key = None
            
            if pending_routing_key is not None:
                key = pending_routing_key
                key_lower = pending_routing_key
                pending_routing_key = None 
            elif raw_key != -1:
                key = raw_key & 0xFF
                key_lower = ord(chr(key).lower()) if 0 <= key < 256 else key
                
            if key_lower is None:
                continue

            # =================================================================
            # MOTOR DE UNDO (CTRL + Z) -> O OpenCV registra Ctrl+Z como ASCII 26
            # =================================================================
            if key == 26: 
                if len(history) > 0:
                    last_act = history.pop()
                    
                    if last_act['type'] == 'box':
                        if last_act['index'] == i:
                            # Restaura as caixas na mesma tela
                            current_boxes = copy.deepcopy(last_act['boxes'])
                            ui_message = "Desfeito: Marcacao"
                            ui_message_timer = 30
                        else:
                            # Se a caixa editada foi de uma imagem anterior, nós voltamos pra ela
                            save_labels(lbl_path, current_boxes)
                            target_lbl_path = os.path.join(labels_dir, os.path.splitext(image_files[last_act['index']])[0] + '.txt')
                            save_labels(target_lbl_path, last_act['boxes']) # Salva a correção no arquivo antigo
                            i = last_act['index']
                            break # Recarrega a tela
                            
                    elif last_act['type'] == 'classification':
                        # Puxa a imagem da pasta da categoria de volta pra raiz
                        if os.path.exists(last_act['moved_img_path']):
                            try: shutil.move(last_act['moved_img_path'], last_act['original_img_path'])
                            except: pass
                        image_files.insert(last_act['index'], last_act['img_name'])
                        save_labels(lbl_path, current_boxes)
                        i = last_act['index']
                        save_progress(labels_dir, i)
                        break 
                        
                    elif last_act['type'] == 'trash':
                        # Puxa da lixeira de volta pra raiz
                        if os.path.exists(last_act['trashed_img_path']):
                            try: shutil.move(last_act['trashed_img_path'], last_act['original_img_path'])
                            except: pass
                        if os.path.exists(last_act['trashed_lbl_path']):
                            try: shutil.move(last_act['trashed_lbl_path'], last_act['original_lbl_path'])
                            except: pass
                        image_files.insert(last_act['index'], last_act['img_name'])
                        save_labels(lbl_path, current_boxes)
                        i = last_act['index']
                        save_progress(labels_dir, i)
                        break
                else:
                    ui_message = "Historico vazio!"
                    ui_message_timer = 20
                continue
            # =================================================================

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
                trash_img_path = os.path.join(trash_img_dir, img_name)
                trash_lbl_path = os.path.join(trash_lbl_dir, os.path.basename(lbl_path))
                
                # Salva no Histórico ANTES de mandar pra lixeira
                push_history({
                    'type': 'trash', 'index': i, 'img_name': img_name,
                    'original_img_path': img_path, 'trashed_img_path': trash_img_path,
                    'original_lbl_path': lbl_path, 'trashed_lbl_path': trash_lbl_path
                })
                
                try: shutil.move(img_path, trash_img_path)
                except: pass
                if os.path.exists(lbl_path): shutil.move(lbl_path, trash_lbl_path)
                image_files.pop(i)
                save_progress(labels_dir, i)
                break
            elif ord('0') <= key <= ord('3'):
                # Salva o Histórico ANTES de mudar a classe da caixa
                push_history({'type': 'box', 'index': current_img_index, 'boxes': copy.deepcopy(current_boxes)})
                nk = key - ord('0')
                idx, _ = get_hit_target(current_mouse_pos[0], current_mouse_pos[1])
                if idx != -1: current_boxes[idx] = (nk, *current_boxes[idx][1:])
                else: active_class = nk
            elif key_lower in MAPA_CLASSIFICACAO_ROTEAMENTO:
                cat_name = MAPA_CLASSIFICACAO_ROTEAMENTO[key_lower]
                cat_img_dir = os.path.join(images_dir, cat_name)
                os.makedirs(cat_img_dir, exist_ok=True)
                new_img_path = os.path.join(cat_img_dir, img_name)
                
                # Salva no Histórico ANTES de classificar
                push_history({
                    'type': 'classification', 'index': i, 'img_name': img_name,
                    'original_img_path': img_path, 'moved_img_path': new_img_path
                })
                
                try: shutil.move(img_path, new_img_path)
                except: pass
                
                save_labels(lbl_path, current_boxes)
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