import os
import shutil
import argparse

def organize_labels(images_dir, labels_dir, output_dir, dry_run=False):
    if not os.path.isdir(images_dir) or not os.path.isdir(labels_dir):
        print(f"Erro: Verifique os diretórios de origem.\nImagens: {images_dir}\nLabels: {labels_dir}")
        return

    valid_extensions = ('.jpg', '.jpeg', '.png')
    arquivos_copiados = 0
    pastas_criadas = set()

    print(f"Lendo a estrutura de imagens em: {images_dir}")
    print(f"Os labels organizados serão salvos em: {output_dir}\n")

    # Passo 1: Varre a pasta de imagens recursivamente
    for root, dirs, files in os.walk(images_dir):
        # Descobre o caminho relativo da pasta atual em relação à pasta raiz de imagens
        # Ex: se root é "images/caminhao_toco", rel_path será "caminhao_toco"
        rel_path = os.path.relpath(root, images_dir)
        
        # Define qual será o diretório de destino para os labels desta subpasta
        target_label_dir = os.path.join(output_dir, rel_path)

        for f in files:
            if f.lower().endswith(valid_extensions):
                base_name = os.path.splitext(f)[0]
                label_src = os.path.join(labels_dir, f"{base_name}.txt")

                # Passo 2: Se o label existir na pasta flat original, prepara a cópia
                if os.path.exists(label_src):
                    label_dest = os.path.join(target_label_dir, f"{base_name}.txt")

                    if dry_run:
                        print(f"[DRY-RUN] Criaria pasta: {target_label_dir}")
                        print(f"[DRY-RUN] Copiaria: {base_name}.txt -> {target_label_dir}")
                    else:
                        try:
                            # Cria a subpasta de destino se ela ainda não existir
                            if target_label_dir not in pastas_criadas:
                                os.makedirs(target_label_dir, exist_ok=True)
                                pastas_criadas.add(target_label_dir)
                            
                            # Copia o arquivo preservando os metadados
                            shutil.copy2(label_src, label_dest)
                            arquivos_copiados += 1
                        except Exception as e:
                            print(f"Erro ao copiar {label_src}: {e}")

    if dry_run:
        print(f"\n[MODO SIMULAÇÃO] {arquivos_copiados} arquivos .txt seriam organizados na nova estrutura.")
    else:
        print(f"\n[SUCESSO] Organização concluída!")
        print(f"-> Labels copiados e organizados: {arquivos_copiados}")
        print(f"-> Estrutura salva em: {output_dir}")

def main():
    parser = argparse.ArgumentParser(description="Reorganiza os arquivos de label espelhando a estrutura de pastas das imagens.")
    parser.add_argument("--images", type=str, required=True, help="Caminho raiz da pasta de imagens (contém as subpastas)")
    parser.add_argument("--labels", type=str, required=True, help="Caminho da pasta onde os labels estão todos misturados")
    parser.add_argument("--output", type=str, required=True, help="Caminho da NOVA pasta onde os labels organizados serão salvos")
    parser.add_argument("--dry-run", action="store_true", help="Mostra o que seria feito sem copiar ou criar pastas de fato")
    
    args = parser.parse_args()
    organize_labels(args.images, args.labels, args.output, args.dry_run)

if __name__ == "__main__":
    main()