import os
import argparse

# ==========================================
# CONFIGURAÇÕES DO DATASET (AJUSTE AQUI)
# ==========================================

# IDs originais no seu dataset que representam os veículos a serem substituídos.
# Ex: No dataset COCO padrão, ônibus = '5' e caminhão = '7'.
CLASSES_PARA_SUBSTITUIR = ['2', '3']

# Mapeamento exato do nome da subpasta para o NOVO ID da classe YOLO.
# Adicione todas as categorias do DNIT que você separou.
MAPA_PASTAS_PARA_ID = {
    "2CB": "2",
    "2C": "3",
    "2S2": "4",
    "3S3": "5",
    "3C": "6",
}
# ==========================================

def update_yolo_labels(images_dir, labels_dir, dry_run=False):
    if not os.path.isdir(images_dir) or not os.path.isdir(labels_dir):
        print(f"Erro: Verifique os diretórios.\nImagens: {images_dir}\nLabels: {labels_dir}")
        return

    valid_extensions = ('.jpg', '.jpeg', '.png')
    arquivos_alterados = 0
    linhas_alteradas = 0

    print(f"Iniciando varredura em: {images_dir}")

    # Passo 1: Busca recursiva nas pastas de imagens
    for root, dirs, files in os.walk(images_dir):
        folder_name = os.path.basename(root).strip()

        # Se a pasta não estiver no nosso mapa, ignora as imagens dela
        if folder_name not in MAPA_PASTAS_PARA_ID:
            continue
            
        novo_id_classe = MAPA_PASTAS_PARA_ID[folder_name]

        for f in files:
            if f.lower().endswith(valid_extensions):
                base_name = os.path.splitext(f)[0]
                label_path = os.path.join(labels_dir, f"{base_name}.txt")

                # Passo 2: Se o label existir, processa as linhas
                if os.path.exists(label_path):
                    with open(label_path, 'r', encoding='utf-8') as file:
                        lines = file.readlines()

                    novas_linhas = []
                    modificou_arquivo = False

                    # Passo 3: Lê linha por linha do formato YOLO (class_id x y w h)
                    for line in lines:
                        parts = line.strip().split()
                        if not parts:
                            continue
                            
                        class_id = parts[0]
                        
                        # Se o class_id estiver na lista de substituição, troca pelo novo ID
                        if class_id in CLASSES_PARA_SUBSTITUIR:
                            parts[0] = novo_id_classe
                            modificou_arquivo = True
                            linhas_alteradas += 1
                        
                        novas_linhas.append(" ".join(parts) + "\n")

                    # Passo 4: Sobrescreve o arquivo label apenas se houve alguma alteração
                    if modificou_arquivo:
                        if dry_run:
                            print(f"[DRY-RUN] Alteraria {label_path} (Pasta: {folder_name} -> Novo ID: {novo_id_classe})")
                        else:
                            try:
                                with open(label_path, 'w', encoding='utf-8') as file:
                                    file.writelines(novas_linhas)
                            except Exception as e:
                                print(f"Erro ao salvar {label_path}: {e}")
                                
                        arquivos_alterados += 1

    if dry_run:
        print(f"\n[MODO SIMULAÇÃO] {linhas_alteradas} veículos seriam atualizados em {arquivos_alterados} arquivos.")
    else:
        print(f"\n[SUCESSO] Atualização concluída!")
        print(f"-> Arquivos modificados: {arquivos_alterados}")
        print(f"-> Veículos (linhas) alterados: {linhas_alteradas}")

def main():
    parser = argparse.ArgumentParser(description="Altera IDs de classes YOLO baseado no nome da pasta da imagem.")
    parser.add_argument("--images", type=str, required=True, help="Caminho raiz da pasta de imagens (contém as subpastas das classes)")
    parser.add_argument("--labels", type=str, required=True, help="Caminho da pasta única com todos os arquivos .txt")
    parser.add_argument("--dry-run", action="store_true", help="Apenas mostra o que seria alterado, sem salvar")
    
    args = parser.parse_args()
    update_yolo_labels(args.images, args.labels, args.dry_run)

if __name__ == "__main__":
    main()