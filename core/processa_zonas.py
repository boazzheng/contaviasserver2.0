import os
import sys
import argparse
import cv2
import json
import numpy as np
import pandas as pd
from shapely.geometry import Point, Polygon

# Variáveis globais para a interface do OpenCV
poligono_atual = []
zonas_definidas = {}

def callback_mouse(event, x, y, flags, param):
    """Captura cliques: Esquerdo adiciona ponto, Direito desfaz o último."""
    global poligono_atual
    if event == cv2.EVENT_LBUTTONDOWN:
        poligono_atual.append((x, y))
    elif event == cv2.EVENT_RBUTTONDOWN:
        if len(poligono_atual) > 0:
            poligono_atual.pop() # Remove o último ponto inserido

def definir_zonas_gui(caminho_imagem):
    global poligono_atual, zonas_definidas
    if not os.path.exists(caminho_imagem):
        print(f"[Erro] Imagem não encontrada: {caminho_imagem}")
        sys.exit(1)
        
    img = cv2.imread(caminho_imagem)
    clone = img.copy()
    
    # --- A CORREÇÃO ESTÁ AQUI ---
    # WINDOW_NORMAL permite que a janela seja redimensionada pelo usuário ou pelo sistema,
    # mantendo as coordenadas reais da imagem intocadas nos bastidores.
    cv2.namedWindow("Definicao de Zonas O-D", cv2.WINDOW_NORMAL)
    
    # Força a janela a abrir em um tamanho confortável (ex: 1280x720) 
    # sem estragar a imagem original de fundo.
    cv2.resizeWindow("Definicao de Zonas O-D", 1280, 720) 
    # --------------------------------
    
    cv2.setMouseCallback("Definicao de Zonas O-D", callback_mouse)

    print("\n--- INSTRUÇÕES DE DESENHO ---")
    print("1. [Botão Esquerdo] Marca os vértices da zona.")
    print("2. [Botão Direito] ou Tecla 'z': APAGA o último vértice desenhado.")
    print("3. Tecla 's': SALVA a zona atual (requer 3+ pontos).")
    print("4. Tecla 'c': CANCELA/Limpa toda a zona atual.")
    print("5. Tecla 'q': CONCLUIR desenho e processar dados.\n")

    while True:
        tela = clone.copy()
        
        # Desenha as zonas já confirmadas
        for nome, pts in zonas_definidas.items():
            pts_arr = np.array(pts, np.int32).reshape((-1, 1, 2))
            cv2.fillPoly(tela, [pts_arr], (0, 255, 0, 50))
            cv2.polylines(tela, [pts_arr], True, (0, 255, 0), 2)
            cv2.putText(tela, nome, pts[0], cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # Desenha a zona que está sendo desenhada agora
        if len(poligono_atual) > 0:
            for i in range(len(poligono_atual) - 1):
                cv2.line(tela, poligono_atual[i], poligono_atual[i+1], (0, 0, 255), 2)
            cv2.circle(tela, poligono_atual[-1], 4, (0, 0, 255), -1) # Destaca o último ponto

        cv2.imshow("Definicao de Zonas O-D", tela)
        key = cv2.waitKey(1) & 0xFF

        if key == ord('s') and len(poligono_atual) >= 3:
            nome_zona = input("Digite o nome da zona (ex: Zona A): ").strip()
            if nome_zona:
                zonas_definidas[nome_zona] = poligono_atual.copy()
                poligono_atual = []
                print(f"[Sucesso] Zona '{nome_zona}' salva.")
        elif key == ord('z'): # Atalho de teclado para desfazer
            if len(poligono_atual) > 0:
                poligono_atual.pop()
        elif key == ord('c'):
            poligono_atual = []
        elif key == ord('q'):
            break

    cv2.destroyAllWindows()
    return zonas_definidas
def salvar_mascara(zonas, caminho_json, caminho_imagem_ref):
    # 1. Salva as coordenadas JSON
    try:
        with open(caminho_json, 'w', encoding='utf-8') as f:
            json.dump(zonas, f, indent=4)
        print(f"[Info] JSON salvo em: {caminho_json}")
    except Exception as e:
        print(f"[Erro] Falha ao salvar JSON: {e}")

    # 2. Gera e salva o croqui visual
    try:
        img_ref = cv2.imread(caminho_imagem_ref)
        if img_ref is not None:
            overlay = img_ref.copy()
            croqui = img_ref.copy()

            for nome_zona, pts in zonas.items():
                pts_arr = np.array(pts, np.int32).reshape((-1, 1, 2))
                
                # Preenche polígono com amarelo semi-transparente e borda sólida
                cv2.fillPoly(overlay, [pts_arr], (0, 255, 255))
                cv2.polylines(overlay, [pts_arr], True, (0, 255, 255), 2)
                
                # Encontra o centro geométrico para colocar a letra
                M = cv2.moments(pts_arr)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                else:
                    cx, cy = pts[0][0], pts[0][1]
                    
                # Borda preta + Letra branca
                tamanho_fonte = 2.0
                cv2.putText(overlay, nome_zona, (cx - 20, cy + 15), cv2.FONT_HERSHEY_DUPLEX, tamanho_fonte, (0, 0, 0), 8)
                cv2.putText(overlay, nome_zona, (cx - 20, cy + 15), cv2.FONT_HERSHEY_DUPLEX, tamanho_fonte, (255, 255, 255), 3)

            # Aplica opacidade de 40% na máscara amarela
            cv2.addWeighted(overlay, 0.4, croqui, 0.6, 0, croqui)

            # Salva o arquivo de imagem
            caminho_croqui = caminho_json.replace('.json', '_croqui.jpg')
            cv2.imwrite(caminho_croqui, croqui)
            print(f"[Sucesso] Croqui gerado e salvo em: {caminho_croqui}")
    except Exception as e:
        print(f"[Erro] Falha ao gerar o croqui visual: {e}")

def carregar_mascara(caminho_arquivo):
    try:
        with open(caminho_arquivo, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[Erro] Falha ao carregar a máscara: {e}")
        sys.exit(1)

def get_posicao(x, y, posicoes):
    point = Point(x, y)
    for pos_nome, poly_coords in posicoes.items():
        polygon = Polygon(poly_coords)
        if polygon.contains(point):
            return pos_nome
    return None

def processar_e_agregar(arquivo_input, arquivo_output, posicoes, hora_inicio_str):
    if not posicoes:
        print("[Erro] Nenhuma zona definida.")
        sys.exit(1)

    print("\n[Info] Processando dados e gerando matriz...")
    try:
        df = pd.read_csv(arquivo_input)
        
        colunas_requeridas = {'start x', 'start y', 'end x', 'end y', 'start timestamp', 'vehicle type'}
        if not colunas_requeridas.issubset(set(df.columns)):
            print(f"[Erro] O CSV precisa conter estas colunas: {colunas_requeridas}")
            sys.exit(1)

        mapa_classes = {
            'car': 'carro', 'motorcycle': 'moto', 'motorbike': 'moto',
            'bus': 'ônibus', 'truck': 'caminhão'
        }
        df['vehicle type'] = df['vehicle type'].astype(str).str.lower().replace(mapa_classes)

        # 1. Aplicar a máscara O-D
        df['origem'] = df.apply(lambda r: get_posicao(r['start x'], r['start y'], posicoes), axis=1)
        df['destino'] = df.apply(lambda r: get_posicao(r['end x'], r['end y'], posicoes), axis=1)
        
        df = df.dropna(subset=['origem', 'destino'])
        
        if df.empty:
            print("[Aviso] Nenhum veículo cruzou as zonas de Origem/Destino desenhadas.")
            categorias_ordem = ['carro', 'moto', 'ônibus', 'caminhão']
            relatorio_vazio = pd.DataFrame(columns=['Movimento', 'Intervalo'] + categorias_ordem)
            relatorio_vazio.to_csv(arquivo_output, index=False, encoding='utf-8')
            sys.exit(0)
            
        df['Movimento'] = df['origem'] + " -> " + df['destino']

        # 2. Lógica Temporal 
        df['start timestamp'] = pd.to_timedelta(df['start timestamp'], errors='coerce')
        df = df.dropna(subset=['start timestamp'])
        
        if df.empty:
            print("[Erro] A coluna 'start timestamp' não possuía formatos de tempo válidos.")
            sys.exit(1)
            
        hora_base = pd.to_datetime(hora_inicio_str, format='%H:%M')
        
        df['Hora_Exata'] = hora_base + df['start timestamp']
        df['Intervalo_Start'] = df['Hora_Exata'].dt.floor('15min')

        # 3. Pivotar os dados
        pivot = df.pivot_table(index=['Movimento', 'Intervalo_Start'], 
                               columns='vehicle type', 
                               aggfunc='size', 
                               fill_value=0).reset_index()

        categorias_ordem = ['carro', 'moto', 'ônibus', 'caminhão']
        for cat in categorias_ordem:
            if cat not in pivot.columns:
                pivot[cat] = 0

        # 4. Preencher Gaps
        hora_min = hora_base.floor('15min')
        hora_max = df['Intervalo_Start'].max()
        if hora_max < hora_min: hora_max = hora_min
        
        intervalos_completos = pd.date_range(start=hora_min, end=hora_max, freq='15min')
        movimentos_unicos = df['Movimento'].unique()
        
        grid = pd.MultiIndex.from_product([movimentos_unicos, intervalos_completos], 
                                          names=['Movimento', 'Intervalo_Start']).to_frame(index=False)
        
        relatorio = pd.merge(grid, pivot, on=['Movimento', 'Intervalo_Start'], how='left').fillna(0)

        # Gerar a string de intervalo final "HH:MM - HH:MM"
        relatorio['Intervalo'] = relatorio['Intervalo_Start'].dt.strftime('%H:%M') + " - " + \
                                (relatorio['Intervalo_Start'] + pd.Timedelta(minutes=15)).dt.strftime('%H:%M')

        for cat in categorias_ordem:
            relatorio[cat] = relatorio[cat].astype(int)
            
        relatorio = relatorio.sort_values(by=['Movimento', 'Intervalo_Start'])
        
        # Exportar
        colunas_finais = ['Movimento', 'Intervalo'] + categorias_ordem
        relatorio_final = relatorio[colunas_finais]
        relatorio_final.to_csv(arquivo_output, index=False, encoding='utf-8')
        print(f"[Sucesso] Relatório final gerado: {arquivo_output}")

    except Exception as e:
        print(f"[Erro Fatal] Falha na manipulação dos dados: {e}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gera matriz temporal O-D baseada em zonas desenhadas.")
    parser.add_argument("-i", "--image", required=True, help="Screenshot do vídeo (.jpg, .png)")
    parser.add_argument("-c", "--csv", required=True, help="CSV bruto da IA")
    parser.add_argument("-t", "--time", required=True, help="Horário inicial (ex: 17:00)")
    parser.add_argument("-o", "--output", help="Caminho do CSV de saída")
    parser.add_argument("-m", "--mask", help="Arquivo JSON da máscara O-D")
    
    args = parser.parse_args()
    output_file = args.output if args.output else os.path.splitext(args.csv)[0] + '_relatorio_final.csv'

    if args.mask and os.path.exists(args.mask):
        zonas_mapeadas = carregar_mascara(args.mask)
    else:
        zonas_mapeadas = definir_zonas_gui(args.image)
        if args.mask and zonas_mapeadas:
            # Envia a imagem de referência para a função salvar_mascara criar o Croqui
            salvar_mascara(zonas_mapeadas, args.mask, args.image)
    
    processar_e_agregar(args.csv, output_file, zonas_mapeadas, args.time)