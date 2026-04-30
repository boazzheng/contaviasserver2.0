import os
import argparse
from collections import defaultdict

def analisar_e_limpar_dataset(root_dir, executar_limpeza=False):
    images_dir = os.path.join(root_dir, 'images')
    labels_dir = os.path.join(root_dir, 'labels')

    if not os.path.isdir(images_dir) or not os.path.isdir(labels_dir):
        print(f"[ERRO CRÍTICO] Estrutura inválida. Certifique-se de que as pastas existem:\n{images_dir}\n{labels_dir}")
        return

    valid_exts = ('.jpg', '.jpeg', '.png')
    stats = defaultdict(lambda: {'imgs': 0, 'lbls': 0})
    total_imgs = 0
    
    # Armazena os nomes das imagens válidas para o cross-check de limpeza
    imagens_validas_basenames = set()

    print(f"Lendo estrutura em: {root_dir}...")

    # 1. Varre as subpastas de imagens
    for root, dirs, files in os.walk(images_dir):
        if root == images_dir:
            continue
            
        categoria = os.path.basename(root)
        
        for f in files:
            if f.lower().endswith(valid_exts):
                stats[categoria]['imgs'] += 1
                total_imgs += 1
                
                base_name = os.path.splitext(f)[0]
                imagens_validas_basenames.add(base_name)
                
                label_path = os.path.join(labels_dir, f"{base_name}.txt")
                if os.path.exists(label_path):
                    stats[categoria]['lbls'] += 1

    # 2. Identifica e processa os labels excedentes (órfãos)
    try:
        labels_soltos = [f for f in os.listdir(labels_dir) if f.lower().endswith('.txt')]
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha ao ler a pasta de labels: {e}")
        return
        
    total_labels_soltos = len(labels_soltos)
    
    labels_para_remover = []
    for label_file in labels_soltos:
        lbl_base = os.path.splitext(label_file)[0]
        if lbl_base not in imagens_validas_basenames:
            labels_para_remover.append(os.path.join(labels_dir, label_file))

    # 3. Exibição do Relatório (Garantindo a Ordem Decrescente)
    print("\n" + "="*65)
    print(" RANKING DE CLASSES DNIT (ORDEM DECRESCENTE DE IMAGENS)")
    print("="*65)
    
    if not stats:
        print("Nenhuma imagem válida encontrada nas subpastas.")
        return

    # Força a extração dos dados para uma lista e ordena rigorosamente pelo valor numérico de 'imgs'
    lista_categorias = list(stats.items())
    categorias_ordenadas = sorted(lista_categorias, key=lambda item: item[1]['imgs'], reverse=True)

    # Imprime com um índice (i) para comprovar a ordem
    for i, (cat, counts) in enumerate(categorias_ordenadas, start=1):
        imgs = counts['imgs']
        lbls = counts['lbls']
        status = "[OK]" if imgs == lbls else "[ALERTA - FALTAM LABELS]"
        
        print(f"{i:02d}. Categoria: {cat.ljust(15)} | Imagens: {str(imgs).ljust(5)} | Labels: {str(lbls).ljust(5)} {status}")

    print("-" * 65)
    print(f"TOTAL DE IMAGENS NAS CATEGORIAS : {total_imgs}")
    print(f"TOTAL DE LABELS NA PASTA RAIZ   : {total_labels_soltos}")
    
    # 4. Lógica de Limpeza
    if labels_para_remover:
        print(f"\n[AVISO] Foram encontrados {len(labels_para_remover)} arquivos .txt sem imagem correspondente.")
        
        if executar_limpeza:
            removidos_com_sucesso = 0
            for lbl_path in labels_para_remover:
                try:
                    os.remove(lbl_path)
                    removidos_com_sucesso += 1
                except Exception as e:
                    print(f"  -> Erro ao remover {os.path.basename(lbl_path)}: {e}")
            print(f"[SUCESSO] Limpeza concluída: {removidos_com_sucesso} labels órfãos deletados.")
        else:
            print(">> Para apagar esses arquivos excedentes, rode o script novamente adicionando a flag --clean")
    else:
        print("\n[SUCESSO] O dataset já está limpo. Não há labels excedentes soltos.")

def main():
    parser = argparse.ArgumentParser(description="Gera relatório de classes e limpa labels excedentes.")
    parser.add_argument("--root", type=str, required=True, help="Caminho para a pasta raiz (com 'images' e 'labels')")
    parser.add_argument("--clean", action="store_true", help="Remove fisicamente os arquivos .txt que não possuem imagem correspondente")
    
    args = parser.parse_args()
    analisar_e_limpar_dataset(args.root, args.clean)

if __name__ == "__main__":
    main()