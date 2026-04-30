import os
import argparse
from collections import defaultdict

def encontrar_fragmentos_dataset(root_dir):
    """Varre a raiz em busca de diretórios com 'images' e 'labels'."""
    fragmentos = []
    pastas_ignoradas = []
    
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames_lower = [d.lower() for d in dirnames]
        
        if 'images' in dirnames_lower and 'labels' in dirnames_lower:
            fragmentos.append(dirpath)
            img_dir = next(d for d in dirnames if d.lower() == 'images')
            lbl_dir = next(d for d in dirnames if d.lower() == 'labels')
            dirnames.remove(img_dir)
            dirnames.remove(lbl_dir)
        else:
            if os.path.dirname(dirpath) == root_dir and dirpath != root_dir:
                pastas_ignoradas.append((dirpath, dirnames))
                
    return fragmentos, pastas_ignoradas

def analisar_e_deduplicar(root_dir, auto_dedup=False, clean_orphans=False):
    root_abs = os.path.abspath(root_dir)

    if not os.path.isdir(root_abs):
        print(f"[ERRO CRÍTICO] Diretório raiz não encontrado: {root_abs}")
        return

    print(f"Iniciando Autodiscover Topológico em: {root_abs}...")
    fragmentos, pastas_ignoradas = encontrar_fragmentos_dataset(root_abs)

    if not fragmentos:
        print("\n[ERRO] Nenhum par de pastas 'images' e 'labels' foi encontrado na estrutura válida.")
        return

    print(f"\n[OK] Encontrados {len(fragmentos)} lotes/fragmentos válidos:")
    for f in fragmentos:
        tipo = "[MONOLITO ANTIGO (RAIZ)]" if os.path.abspath(f) == root_abs else "[NOVO LOTE FEDERADO]"
        print(f" -> {f} {tipo}")

    valid_exts = ('.jpg', '.jpeg', '.png')
    imagens_por_basename = defaultdict(list)

    # 1. PASSO DE MAPEAMENTO GLOBAL DAS IMAGENS
    for fragmento_dir in fragmentos:
        subpastas = os.listdir(fragmento_dir)
        img_folder_name = next(d for d in subpastas if d.lower() == 'images')
        lbl_folder_name = next(d for d in subpastas if d.lower() == 'labels')
        
        images_dir = os.path.join(fragmento_dir, img_folder_name)
        labels_dir = os.path.join(fragmento_dir, lbl_folder_name)

        for root, dirs, files in os.walk(images_dir):
            if root == images_dir: continue 
            categoria = os.path.basename(root)
            
            for f in files:
                if f.lower().endswith(valid_exts):
                    base_name = os.path.splitext(f)[0]
                    img_path = os.path.join(root, f)
                    lbl_path = os.path.join(labels_dir, f"{base_name}.txt")
                    
                    imagens_por_basename[base_name].append({
                        'fragmento': fragmento_dir,
                        'img_path': img_path,
                        'lbl_path': lbl_path,
                        'categoria': categoria,
                        'tem_label': os.path.exists(lbl_path)
                    })

    # 2. PASSO DE RESOLUÇÃO DE CONFLITOS (AUTO-DEDUP)
    conflitos_resolvidos = 0
    conflitos_nao_resolvidos = []

    for base_name, ocorrencias in list(imagens_por_basename.items()):
        if len(ocorrencias) > 1:
            if auto_dedup:
                m_items = [i for i in ocorrencias if os.path.abspath(i['fragmento']) == root_abs]
                f_items = [i for i in ocorrencias if os.path.abspath(i['fragmento']) != root_abs]

                if m_items and f_items:
                    for m in m_items:
                        try:
                            os.remove(m['img_path'])
                            if m['tem_label']:
                                os.remove(m['lbl_path'])
                            ocorrencias.remove(m)
                            conflitos_resolvidos += 1
                        except Exception as e:
                            pass

            if len(ocorrencias) > 1:
                conflitos_nao_resolvidos.append((base_name, ocorrencias))

    # 3. CONSTRUÇÃO DO RELATÓRIO E CAÇA AOS ÓRFÃOS
    stats_globais = defaultdict(lambda: {'imgs': 0, 'lbls': 0})
    total_imgs_global = 0

    for base_name, ocorrencias in imagens_por_basename.items():
        for item in ocorrencias:
            stats_globais[item['categoria']]['imgs'] += 1
            total_imgs_global += 1
            if item['tem_label']:
                stats_globais[item['categoria']]['lbls'] += 1

    total_labels_soltos_global = 0
    labels_orfaos = [] # RASTREADOR DE FANTASMAS

    for fragmento_dir in fragmentos:
        subpastas = os.listdir(fragmento_dir)
        lbl_folder_name = next(d for d in subpastas if d.lower() == 'labels')
        labels_dir = os.path.join(fragmento_dir, lbl_folder_name)
        
        try:
            for f in os.listdir(labels_dir):
                if f.lower().endswith('.txt'):
                    total_labels_soltos_global += 1
                    lbl_base = os.path.splitext(f)[0]
                    # Se o txt existe, mas não está no mapeamento global de imagens = Órfão
                    if lbl_base not in imagens_por_basename:
                        labels_orfaos.append(os.path.join(labels_dir, f))
        except Exception as e:
            pass

    # 4. EXIBIÇÃO
    print("\n" + "="*75)
    print(" RANKING GLOBAL DE CLASSES DNIT (DATASET FEDERADO)")
    print("="*75)
    
    categorias_ordenadas = sorted(stats_globais.items(), key=lambda item: item[1]['imgs'], reverse=True)
    for i, (cat, counts) in enumerate(categorias_ordenadas, start=1):
        imgs = counts['imgs']
        lbls = counts['lbls']
        status = "[OK]" if imgs == lbls else "[ALERTA - FALTAM LABELS]"
        print(f"{i:02d}. Categoria: {cat.ljust(15)} | Imagens: {str(imgs).ljust(5)} | Labels: {str(lbls).ljust(5)} {status}")

    print("-" * 75)
    print(f"TOTAL GLOBAL DE IMAGENS NAS CATEGORIAS : {total_imgs_global}")
    print(f"TOTAL GLOBAL DE LABELS FÍSICOS         : {total_labels_soltos_global}")

    # LOGS DE AÇÃO
    if auto_dedup and conflitos_resolvidos > 0:
        print(f"\n[SUCESSO] AUTO-DEDUPLICAÇÃO: {conflitos_resolvidos} imagens/labels removidos do Monolito Antigo (Raiz).")

    if labels_orfaos:
        print("\n" + "!"*75)
        print(f" ALERTA: Foram encontrados {len(labels_orfaos)} arquivos .txt ÓRFÃOS (sem imagem).")
        print("!"*75)
        
        if clean_orphans:
            removidos = 0
            for lbl_path in labels_orfaos:
                try:
                    os.remove(lbl_path)
                    removidos += 1
                except:
                    pass
            print(f"[SUCESSO] Limpeza concluída: {removidos} labels fantasmas foram deletados.")
            print(">> Rode o script novamente para ver os números perfeitamente alinhados.")
        else:
            print(">> Para deletar esses arquivos inúteis, rode com a flag --clean-orphans")

    if conflitos_nao_resolvidos:
        print("\n" + "!"*80)
        print(f" ALERTA CRÍTICO: {len(conflitos_nao_resolvidos)} COLISÕES NÃO RESOLVIDAS!")
        for base_name, ocorrencias in conflitos_nao_resolvidos:
            print(f"\n[Conflito]: {base_name}.jpg")
            for item in ocorrencias:
                print(f"  -> {item['img_path']}")

    if not conflitos_nao_resolvidos and not labels_orfaos:
        print("\n[SUCESSO] Nenhuma colisão pendente e nenhum órfão. Dataset Federado 100% perfeito!")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=str, required=True)
    parser.add_argument("--auto-dedup", action="store_true", help="Remove duplicações do monolito")
    parser.add_argument("--clean-orphans", action="store_true", help="Remove arquivos .txt que não têm imagem")
    args = parser.parse_args()
    analisar_e_deduplicar(args.root, args.auto_dedup, args.clean_orphans)

if __name__ == "__main__":
    main()