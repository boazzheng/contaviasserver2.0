import os
import argparse
import glob

def sync_dataset_folders(images_dir, labels_dir, dry_run=False):
    if not os.path.isdir(images_dir) or not os.path.isdir(labels_dir):
        print(f"Erro crítico: Verifique os diretórios.\nImagens: {images_dir}\nLabels: {labels_dir}")
        return

    valid_extensions = ('.jpg', '.jpeg', '.png')
    
    # Passo 1: Coletar os "nomes base" (NORMALIZADOS)
    print(f"Lendo imagens recursivamente em: {images_dir}")
    image_basenames = set()
    
    for root, dirs, files in os.walk(images_dir):
        for f in files:
            if f.lower().endswith(valid_extensions):
                # Extrai o nome, remove espaços em branco nas pontas e força minúsculo
                name_without_ext = os.path.splitext(f)[0].strip().lower()
                image_basenames.add(name_without_ext)

    print(f"Total de imagens válidas encontradas: {len(image_basenames)}")
    
    if not image_basenames:
        print("Aviso: Nenhuma imagem encontrada. Abortando.")
        return

    # Passo 2: Procurar arquivos .txt órfãos
    label_files = glob.glob(os.path.join(labels_dir, "*.txt"))
    if not label_files:
        print("Aviso: Nenhum arquivo .txt encontrado no diretório de labels.")
        return
        
    removed_count = 0
    debug_samples_shown = 0

    print("Verificando arquivos de anotação (.txt)...")
    for label_path in label_files:
        filename = os.path.basename(label_path)
        # Normaliza também o nome do label para a comparação
        name_without_ext = os.path.splitext(filename)[0].strip().lower()

        # Passo 3: Verifica se o nome normalizado está no set
        if name_without_ext not in image_basenames:
            if dry_run:
                # print(f"[DRY-RUN] Seria deletado: {filename}")
                
                # Exibe um debug profundo apenas para os 3 primeiros casos
                if debug_samples_shown < 3:
                    print(f"   -> MOTIVO: O label normalizado '{name_without_ext}' não tem par exato.")
                    # Pega até 3 exemplos do set de imagens para o usuário comparar visualmente
                    sample_imgs = list(image_basenames)[:3]
                    print(f"   -> EXEMPLOS NA MEMÓRIA: {sample_imgs}\n")
                    debug_samples_shown += 1
            else:
                try:
                    os.remove(label_path)
                    print(f"Deletado: {filename}")
                except Exception as e:
                    print(f"Erro ao deletar {filename}: {e}")
            removed_count += 1

    if dry_run:
        print(f"\n[Modo de Teste] {removed_count} arquivos .txt seriam deletados.")
        if removed_count > 500:
            print("\n⚠️ ALERTA DE DEBUG: O número de deleções ainda está muito alto.")
            print("Olhe os 'MOTIVOS' impressos acima. Se as strings forem completamente diferentes (ex: imagens chamam 'frame01' e labels 'img01'), você precisará de uma regra de regex para mapear o padrão.")
    else:
        print(f"\nLimpeza concluída. {removed_count} arquivos .txt órfãos foram deletados.")

def main():
    parser = argparse.ArgumentParser(description="Sincroniza pasta de labels com imagens (normalização rigorosa).")
    parser.add_argument("--images", type=str, required=True, help="Caminho raiz para a pasta de imagens")
    parser.add_argument("--labels", type=str, required=True, help="Caminho para a pasta de labels")
    parser.add_argument("--dry-run", action="store_true", help="Simula a exclusão e exibe o motivo da incompatibilidade")
    
    args = parser.parse_args()
    sync_dataset_folders(args.images, args.labels, args.dry_run)

if __name__ == "__main__":
    main()