import os
import shutil
import random
import argparse
import yaml

# ==========================================
# CONFIGURAÇÕES DE CLASSES (Mesmas do passo anterior)
# ==========================================
MAPA_PASTAS = {
    "2C": "10",
    "2CB": "11",
    "2S2": "12",
    "3S3": "13",
    "3C": "14",
}
# ==========================================

def prepare_yolo_dataset(images_dir, labels_dir, output_dir, split_ratio=0.8):
    if not os.path.exists(images_dir) or not os.path.exists(labels_dir):
        print("Erro crítico: Diretórios de origem não encontrados.")
        return

    # Passo 1: Criar a estrutura rigorosa do YOLO
    dirs_to_create = [
        os.path.join(output_dir, 'images', 'train'),
        os.path.join(output_dir, 'images', 'val'),
        os.path.join(output_dir, 'labels', 'train'),
        os.path.join(output_dir, 'labels', 'val')
    ]
    
    for d in dirs_to_create:
        os.makedirs(d, exist_ok=True)

    valid_extensions = ('.jpg', '.jpeg', '.png')
    dataset_pairs = []

    print("Varrendo arquivos e pareando Imagens + Labels...")

    # Passo 2: Coletar todos os pares válidos
    for root, _, files in os.walk(images_dir):
        folder_name = os.path.basename(root).strip()
        if folder_name not in MAPA_PASTAS:
            continue

        for f in files:
            if f.lower().endswith(valid_extensions):
                base_name = os.path.splitext(f)[0]
                img_path = os.path.join(root, f)
                
                # O label correspondente tem que estar no espelho exato
                rel_path = os.path.relpath(root, images_dir)
                label_path = os.path.join(labels_dir, rel_path, f"{base_name}.txt")

                if os.path.exists(label_path):
                    dataset_pairs.append({
                        'img_src': img_path,
                        'lbl_src': label_path,
                        'folder': folder_name, # Usado para prefixo de segurança
                        'basename': base_name,
                        'ext': os.path.splitext(f)[1]
                    })

    total_pairs = len(dataset_pairs)
    if total_pairs == 0:
        print("Erro: Nenhum par de Imagem+Label encontrado. Verifique os caminhos.")
        return

    # Passo 3: Embaralhar e dividir (80/20) - Seed fixo para reprodutibilidade
    random.seed(42)
    random.shuffle(dataset_pairs)
    
    train_size = int(total_pairs * split_ratio)
    train_pairs = dataset_pairs[:train_size]
    val_pairs = dataset_pairs[train_size:]

    print(f"Total pareado: {total_pairs} | Treino: {len(train_pairs)} | Validação: {len(val_pairs)}")

    # Passo 4: Função para copiar e nivelar
    def copy_split(pairs, split_name):
        print(f"Copiando dados de {split_name}...")
        for item in pairs:
            # PREFIXO DEFENSIVO: Evita que "img01.jpg" da pasta Toco sobrescreva "img01.jpg" da pasta Bitrem
            safe_basename = f"{item['folder'].replace(' ', '_')}_{item['basename']}"
            
            new_img_path = os.path.join(output_dir, 'images', split_name, f"{safe_basename}{item['ext']}")
            new_lbl_path = os.path.join(output_dir, 'labels', split_name, f"{safe_basename}.txt")
            
            shutil.copy2(item['img_src'], new_img_path)
            shutil.copy2(item['lbl_src'], new_lbl_path)

    copy_split(train_pairs, 'train')
    copy_split(val_pairs, 'val')

    # Passo 5: Gerar o arquivo data.yaml exigido pelo YOLO
    yaml_path = os.path.join(output_dir, 'data.yaml')
    
    # Escreva o dicionário COMPLETO (A Fonte Absoluta da Verdade)
    # Garante que o YOLO saiba quem é o 0 e o 1, mesmo que você não tenha pastas para eles
    yaml_content = {
        'path': os.path.abspath(output_dir), 
        'train': 'images/train',
        'val': 'images/val',
        'names': {
            0: 'carro',
            1: 'moto',
            2: '2CB',
            3: '2C',
            4: '2S2',
            5: '3S3',
            6: '3C'
        }
    }

    try:
        with open(yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(yaml_content, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        print(f"\n[SUCESSO] data.yaml criado em: {yaml_path}")
    except Exception as e:
        print(f"Erro ao criar data.yaml: {e}")

    print(f"\nDataset YOLO finalizado! Pronto para treinamento em: {output_dir}")

def main():
    parser = argparse.ArgumentParser(description="Prepara o dataset no padrão YOLO (Train/Val e data.yaml).")
    parser.add_argument("--images", type=str, required=True, help="Pasta de imagens organizadas")
    parser.add_argument("--labels", type=str, required=True, help="Pasta de labels organizados")
    parser.add_argument("--output", type=str, required=True, help="Pasta final para o dataset YOLO")
    parser.add_argument("--split", type=float, default=0.8, help="Proporção para treino (padrão 0.8 -> 80%)")
    
    args = parser.parse_args()
    prepare_yolo_dataset(args.images, args.labels, args.output, args.split)

if __name__ == "__main__":
    main()