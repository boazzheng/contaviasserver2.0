import os
import argparse
import glob

def sync_dataset_folders(images_dir, labels_dir, dry_run=False):
    """
    Remove arquivos .txt no diretório de labels que não possuem
    uma imagem correspondente no diretório de imagens.
    """
    if not os.path.isdir(images_dir) or not os.path.isdir(labels_dir):
        print(f"Erro: Verifique os diretórios.\nImagens: {images_dir}\nLabels: {labels_dir}")
        return

    # Mapeia as extensões de imagens permitidas
    valid_extensions = ('.jpg', '.jpeg', '.png')
    
    # Passo 1: Coletar os "nomes base" (sem extensão) de todas as imagens que sobraram
    print(f"Lendo imagens em: {images_dir}")
    image_files = os.listdir(images_dir)
    image_basenames = set()
    for f in image_files:
        if f.lower().endswith(valid_extensions):
            name_without_ext = os.path.splitext(f)[0]
            image_basenames.add(name_without_ext)

    print(f"Total de imagens válidas encontradas: {len(image_basenames)}")

    # Passo 2: Procurar arquivos .txt órfãos na pasta de labels
    label_files = glob.glob(os.path.join(labels_dir, "*.txt"))
    removed_count = 0

    print("Verificando arquivos de anotação (.txt)...")
    for label_path in label_files:
        filename = os.path.basename(label_path)
        name_without_ext = os.path.splitext(filename)[0]

        # Passo 3: Se o nome do .txt não estiver no set de imagens, ele é deletado
        if name_without_ext not in image_basenames:
            if dry_run:
                print(f"[DRY-RUN] Seria deletado: {filename}")
            else:
                try:
                    os.remove(label_path)
                    print(f"Deletado: {filename}")
                except Exception as e:
                    print(f"Erro ao deletar {filename}: {e}")
            removed_count += 1

    # Resumo final
    if dry_run:
        print(f"\n[Modo de Teste] {removed_count} arquivos .txt seriam deletados.")
        print("Para deletar de verdade, rode o script sem a flag --dry-run.")
    else:
        print(f"\nLimpeza concluída. {removed_count} arquivos .txt órfãos foram deletados.")

def main():
    parser = argparse.ArgumentParser(description="Sincroniza pasta de labels com imagens (remove .txt órfãos).")
    parser.add_argument("--images", type=str, required=True, help="Caminho para a pasta de imagens")
    parser.add_argument("--labels", type=str, required=True, help="Caminho para a pasta de labels")
    parser.add_argument("--dry-run", action="store_true", help="Simula a exclusão sem apagar os arquivos de fato")
    
    args = parser.parse_args()
    sync_dataset_folders(args.images, args.labels, args.dry_run)

if __name__ == "__main__":
    main()

# python sync_labels.py --images C:\dados\dataset_caminhoes\images --labels C:\dados\dataset_caminhoes\labels --dry-run