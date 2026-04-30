import os
import re
from collections import Counter

def diagnosticar_por_ponto(root_dir):
    images_dir = os.path.join(root_dir, 'images')
    labels_dir = os.path.join(root_dir, 'labels')

    if not os.path.isdir(images_dir) or not os.path.isdir(labels_dir):
        print(f"[ERRO] Verifique se as pastas existem em: {root_dir}")
        return

    # 1. Coleta e separa os nomes (sem extensão)
    nomes_imagens = set()
    for root, _, files in os.walk(images_dir):
        for f in files:
            if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                nomes_imagens.add(os.path.splitext(f)[0])

    nomes_labels = set()
    for f in os.listdir(labels_dir):
        if f.lower().endswith('.txt'):
            nomes_labels.add(os.path.splitext(f)[0])

    # 2. Matemática de Conjuntos
    imagens_sem_label = nomes_imagens - nomes_labels
    labels_orfaos = nomes_labels - nomes_imagens

    # 3. Função Regex para extrair o "Ponto"
    # Captura tudo desde o início (^) até encontrar "_truck_" ou "_bus_"
    padrao = re.compile(r'^(.*?)_(?:truck|bus)_', re.IGNORECASE)

    def extrair_ponto(nome_arquivo):
        match = padrao.search(nome_arquivo)
        if match:
            return match.group(1)
        return "[Fora do Padrão de Nomenclatura]"

    # 4. Agrupamento e Contagem
    contagem_sem_label = Counter([extrair_ponto(n) for n in imagens_sem_label])
    contagem_orfaos = Counter([extrair_ponto(n) for n in labels_orfaos])

    # 5. Exibição do Relatório
    print("\n" + "="*70)
    print(" 🕵️ DIAGNÓSTICO DE DESCOLAMENTO POR PONTO (LOTE)")
    print("="*70)

    print(f"\n[ IMAGENS SEM LABEL - Total: {len(imagens_sem_label)} ]")
    if not contagem_sem_label:
        print(" -> Tudo limpo! Nenhuma imagem está sem anotação.")
    else:
        for ponto, qtd in contagem_sem_label.most_common():
            print(f" -> Ponto: {ponto.ljust(35)} | Imagens sem .txt: {qtd}")

    print("\n" + "-"*70)

    print(f"\n[ LABELS ÓRFÃOS - Total: {len(labels_orfaos)} ]")
    if not contagem_orfaos:
        print(" -> Tudo limpo! Nenhum label fantasma.")
    else:
        for ponto, qtd in contagem_orfaos.most_common():
            print(f" -> Ponto: {ponto.ljust(35)} | Labels sem Imagem: {qtd}")

    print("\n" + "="*70)
    print(">> ANÁLISE:")
    print("Se um ponto aparece apenas em 'Labels Órfãos', significa que você provavelmente não copiou as imagens dele para a pasta.")
    print("Se aparece em 'Imagens sem Label', você copiou as imagens, mas não trouxe os arquivos .txt.")

if __name__ == "__main__":
    # Ajuste para a sua pasta real
    pasta_alvo = r"C:\Users\BoazZheng\Downloads\Categorizados_v2"
    diagnosticar_por_ponto(pasta_alvo)