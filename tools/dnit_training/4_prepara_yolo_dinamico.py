import os
import shutil
import random
import argparse
import yaml
from collections import defaultdict

# ==============================================================================
# CONFIGURAÇÃO DE TRANSIÇÃO
# ==============================================================================
CLASSES_ANTIGAS_ALVO = ['2', '3']

def encontrar_fragmentos_dataset(root_dir):
    fragmentos = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames_lower = [d.lower() for d in dirnames]
        if 'images' in dirnames_lower and 'labels' in dirnames_lower:
            fragmentos.append(dirpath)
            img_dir = next(d for d in dirnames if d.lower() == 'images')
            lbl_dir = next(d for d in dirnames if d.lower() == 'labels')
            dirnames.remove(img_dir)
            dirnames.remove(lbl_dir)
    return fragmentos

def processar_e_copiar(pairs, split_name, output_dir, mapa_dinamico):
    for item in pairs:
        safe_basename = f"{item['categoria'].replace(' ', '_')}_{item['basename']}"
        new_img_path = os.path.join(output_dir, 'images', split_name, f"{safe_basename}{item['ext']}")
        new_lbl_path = os.path.join(output_dir, 'labels', split_name, f"{safe_basename}.txt")
        
        # 1. Copia a imagem fisicamente
        shutil.copy2(item['img_src'], new_img_path)
        
        # 2. Transmuta o Label On-The-Fly com o ID dinâmico
        novo_id_classe = str(mapa_dinamico[item['categoria']])
        novas_linhas = []
        
        with open(item['lbl_src'], 'r', encoding='utf-8') as file:
            for line in file:
                parts = line.strip().split()
                if not parts: continue
                    
                class_id = parts[0]
                if class_id in CLASSES_ANTIGAS_ALVO:
                    parts[0] = novo_id_classe
                    
                novas_linhas.append(" ".join(parts) + "\n")
                
        with open(new_lbl_path, 'w', encoding='utf-8') as new_file:
            new_file.writelines(novas_linhas)

def preparar_dataset_dinamico(root_dir, output_dir, top_k, limite, split_ratio=0.8):
    root_abs = os.path.abspath(root_dir)
    out_abs = os.path.abspath(output_dir)
    
    if root_abs == out_abs:
        print("[ERRO] O diretório de saída não pode ser o mesmo do diretório raiz.")
        return

    print(f"Lendo Dataset Federado em: {root_abs}...")
    fragmentos = encontrar_fragmentos_dataset(root_abs)
    
    if not fragmentos:
        print("[ERRO] Nenhum lote encontrado.")
        return

    valid_exts = ('.jpg', '.jpeg', '.png')
    pares_por_categoria = defaultdict(list)

    # 1. COLETAR TODOS OS DADOS BRUTOS DISPONÍVEIS
    for fragmento_dir in fragmentos:
        subpastas = os.listdir(fragmento_dir)
        img_folder_name = next(d for d in subpastas if d.lower() == 'images')
        lbl_folder_name = next(d for d in subpastas if d.lower() == 'labels')
        
        images_dir = os.path.join(fragmento_dir, img_folder_name)
        labels_dir = os.path.join(fragmento_dir, lbl_folder_name)

        for root, _, files in os.walk(images_dir):
            if root == images_dir: continue
            categoria = os.path.basename(root)

            for f in files:
                if f.lower().endswith(valid_exts):
                    base_name = os.path.splitext(f)[0]
                    img_path = os.path.join(root, f)
                    lbl_path = os.path.join(labels_dir, f"{base_name}.txt")

                    if os.path.exists(lbl_path):
                        pares_por_categoria[categoria].append({
                            'img_src': img_path,
                            'lbl_src': lbl_path,
                            'categoria': categoria,
                            'basename': base_name,
                            'ext': os.path.splitext(f)[1]
                        })

    # 2. DEFINIR O TOP-K CATEGORIAS
    # Ordena as categorias da que tem mais imagens para a que tem menos
    ranking = sorted(pares_por_categoria.items(), key=lambda x: len(x[1]), reverse=True)
    
    if top_k > len(ranking):
        print(f"[AVISO] Você pediu o Top {top_k}, mas o dataset só possui {len(ranking)} categorias válidas.")
        top_k = len(ranking)

    top_categorias = ranking[:top_k]

    print("\n" + "="*65)
    print(f" SELEÇÃO DINÂMICA (TOP {top_k} CATEGORIAS)")
    print("="*65)
    
    # 3. VALIDAÇÃO DE LIMITE (CHECK MATEMÁTICO)
    # A categoria do Top-K com menos imagens é a última da lista (índice -1)
    menor_qtd_no_top = len(top_categorias[-1][1])
    
    for i, (cat, pares) in enumerate(top_categorias, start=1):
        print(f"{i:02d}. {cat.ljust(15)} : {len(pares)} imagens disponíveis")

    if limite > menor_qtd_no_top:
        print("\n" + "!"*65)
        print(f" [ERRO DE BALANCEAMENTO] O limite de {limite} não é possível.")
        print(f" A categoria '{top_categorias[-1][0]}' do seu Top {top_k} possui apenas {menor_qtd_no_top} imagens.")
        print(f" >> Solução: Reduza o parâmetro --limit para no máximo {menor_qtd_no_top} ou diminua o --top.")
        print("!"*65)
        return

    # 4. MAPEAR IDs DINAMICAMENTE (Começando do 2)
    mapa_dinamico = {}
    novo_id = 2
    for cat, _ in top_categorias:
        mapa_dinamico[cat] = novo_id
        novo_id += 1

    # 5. AMOSTRAGEM E DIVISÃO (SAMPLING & SPLITTING)
    random.seed(42)
    train_pairs = []
    val_pairs = []

    print("-" * 65)
    for cat, pares in top_categorias:
        random.shuffle(pares)
        selecionados = pares[:limite]
        
        t_size = int(limite * split_ratio)
        train_pairs.extend(selecionados[:t_size])
        val_pairs.extend(selecionados[t_size:])

    print(f"-> Cada uma das {top_k} categorias fornecerá {limite} imagens.")
    print(f"TOTAL TREINO    : {len(train_pairs)} imagens")
    print(f"TOTAL VALIDAÇÃO : {len(val_pairs)} imagens")

    # 6. PROCESSAMENTO, CÓPIA E CRIAÇÃO DE PASTAS
    dirs_to_create = [
        os.path.join(out_abs, 'images', 'train'), os.path.join(out_abs, 'images', 'val'),
        os.path.join(out_abs, 'labels', 'train'), os.path.join(out_abs, 'labels', 'val')
    ]
    for d in dirs_to_create:
        os.makedirs(d, exist_ok=True)

    print("\nGerando arquivos de Treinamento...")
    processar_e_copiar(train_pairs, 'train', out_abs, mapa_dinamico)
    
    print("Gerando arquivos de Validação...")
    processar_e_copiar(val_pairs, 'val', out_abs, mapa_dinamico)

    # 7. GERAÇÃO DO DATA.YAML
    yaml_path = os.path.join(out_abs, 'data.yaml')
    
    nomes_classes = {0: 'carro', 1: 'moto'}
    for cat, idx in mapa_dinamico.items():
        nomes_classes[idx] = cat

    # Ordena as classes pelo ID
    nomes_classes_ordenados = {k: nomes_classes[k] for k in sorted(nomes_classes)}

    yaml_content = {
        'path': out_abs, 
        'train': 'images/train',
        'val': 'images/val',
        'names': nomes_classes_ordenados
    }

    try:
        with open(yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(yaml_content, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        print("\n[SUCESSO] data.yaml criado! Mapeamento de classes:")
        for idx, nome in nomes_classes_ordenados.items():
            print(f"  [{idx}] -> {nome}")
    except Exception as e:
        print(f"[ERRO] Falha ao criar data.yaml: {e}")

    print(f"\n[FINALIZADO] Dataset YOLO balanceado gerado com sucesso em: {out_abs}")

def main():
    parser = argparse.ArgumentParser(description="Gera o dataset YOLO dinamicamente baseado nas Top-K categorias.")
    parser.add_argument("--root", type=str, required=True, help="Pasta raiz (Federada) original")
    parser.add_argument("--output", type=str, required=True, help="Pasta de saída do dataset YOLO")
    parser.add_argument("--top", type=int, required=True, help="Quantas categorias usar (ex: 5 para o Top 5)")
    parser.add_argument("--limit", type=int, required=True, help="Quantidade de imagens por categoria")
    parser.add_argument("--split", type=float, default=0.8, help="Proporção para treino (padrão 0.8)")
    
    args = parser.parse_args()
    preparar_dataset_dinamico(args.root, args.output, args.top, args.limit, args.split)

if __name__ == "__main__":
    main()