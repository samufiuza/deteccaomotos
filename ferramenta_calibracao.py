"""
Ferramenta de apoio: extrai um quadro do vídeo e deixa você marcar, clicando
com o mouse, a calibração da câmera e as zonas de risco — sem precisar
adivinhar coordenadas.

Uso:
    python ferramenta_calibracao.py --source video.mp4 --frame 100
    python ferramenta_calibracao.py --source frame_live.jpg        # imagem

    --frame: qual quadro do vídeo extrair (padrão 0). Escolha um quadro em que
             o chão esteja bem visível, sem veículos tampando os pontos.
    --saida: arquivo JSON de saída (padrão calibracao_resultado.json). Zonas e
             homografia ficam no MESMO arquivo e podem ser passadas juntas ao
             main.py (--calib-arquivo e --zonas apontando para ele).

CALIBRAÇÃO POR HOMOGRAFIA (recomendada para câmeras inclinadas/urbanas):
    h   começa. Clique 4 pontos NO CHÃO formando um RETÂNGULO real, nesta ordem:
            P1 perto-esquerda -> P2 perto-direita -> P3 longe-direita -> P4 longe-esquerda
        (P1->P2 e P3->P4 = largura; P2->P3 e P4->P1 = comprimento)
    k   confirma: o terminal pede a largura e o comprimento reais, em metros
        (meça no Google Maps, vista de satélite, ou use medidas padrão da via)
    g   liga/desliga uma grade de 1 em 1 metro sobre o retângulo — as linhas
        precisam ficar paralelas às bordas/faixas da rua; se não ficarem,
        refaça os pontos
    v   VALIDAR: clique 2 pontos de OUTRA distância que você conheça (ex.: outra
        largura de pista, vão entre faixas). O terminal mostra a distância
        calculada — compare com a real antes de confiar na calibração

OUTRAS TECLAS:
    c   calibração SIMPLES (2 pontos + distância; só serve para câmera quase
        de cima, sem perspectiva — veja o README)
    z   modo ZONA: clique os pontos do polígono; 'n' fecha e nomeia a zona
    r   apaga os pontos ainda não confirmados (a homografia confirmada fica)
    q   sair e salvar; imprime o comando pronto para o main.py
"""

import argparse
import json

import cv2
import numpy as np

from calibration import (
    calcular_homografia,
    distancia_no_chao,
    salvar_calibracao,
)

JANELA = "Calibracao"

pontos_calibracao = []   # calibração simples: até 2 pontos
zonas = []               # [{"nome": str, "poligono": [(x,y), ...]}]
poligono_atual = []
pontos_chao = []         # até 4 pontos clicados no modo homografia
homografia = None        # {"H": ndarray, "mundo": [(X,Y)x4]} depois de confirmada
medidas = []             # [(p1, p2, metros)] feitas no modo validar
ponto_medida = []        # pontos pendentes do modo validar
mostrar_grade = False
modo = None              # None | "calibracao" | "zona" | "homografia" | "validar"

ROTULOS_CHAO = ["P1 perto-esq", "P2 perto-dir", "P3 longe-dir", "P4 longe-esq"]


# ---------------------------------------------------------------------
# Funções de cálculo (sem interface — testáveis)
# ---------------------------------------------------------------------

def extrair_frame(source, indice_frame):
    cap = cv2.VideoCapture(source)
    cap.set(cv2.CAP_PROP_POS_FRAMES, indice_frame)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        raise RuntimeError(f"Não foi possível ler o frame {indice_frame} de {source}")
    return frame


def quadrilatero_valido(pontos):
    """
    Verifica se 4 pontos formam um quadrilátero convexo na ordem clicada
    (sem cruzar lados). Um retângulo do chão sempre aparece assim na imagem.
    """
    if len(pontos) != 4:
        return False
    sinais = []
    for i in range(4):
        x1, y1 = pontos[i]
        x2, y2 = pontos[(i + 1) % 4]
        x3, y3 = pontos[(i + 2) % 4]
        cruz = (x2 - x1) * (y3 - y2) - (y2 - y1) * (x3 - x2)
        if cruz == 0:
            return False
        sinais.append(cruz > 0)
    return all(sinais) or not any(sinais)


def finalizar_homografia(pontos_imagem, largura_m, comprimento_m):
    """
    pontos_imagem na ordem P1 perto-esq, P2 perto-dir, P3 longe-dir, P4 longe-esq.
    Retorna (H, mundo): H leva pixels -> metros; mundo são as coordenadas reais
    do retângulo, com P1 na origem.
    """
    if largura_m <= 0 or comprimento_m <= 0:
        raise ValueError("Largura e comprimento precisam ser positivos.")
    if not quadrilatero_valido(pontos_imagem):
        raise ValueError(
            "Os 4 pontos não formam um quadrilátero convexo na ordem pedida "
            "(perto-esq, perto-dir, longe-dir, longe-esq). Refaça com 'h'."
        )
    mundo = [(0.0, 0.0), (largura_m, 0.0), (largura_m, comprimento_m), (0.0, comprimento_m)]
    return calcular_homografia(pontos_imagem, mundo), mundo


def medir_no_chao(H, p1, p2):
    """Distância em metros, no chão, entre dois pontos da imagem."""
    return distancia_no_chao(H, p1, p2)


def desenhar_grade(frame, H, mundo):
    """
    Desenha, sobre o retângulo calibrado, uma grade de 1 em 1 metro (5 em 5
    metros se o trecho tiver mais de 15 m), reprojetada na imagem com a
    inversa da homografia. Retas do chão continuam retas na imagem, então
    basta ligar as pontas de cada linha.
    """
    Hinv = np.linalg.inv(H)

    def proj(X, Y):
        v = Hinv @ np.array([X, Y, 1.0])
        if abs(v[2]) < 1e-12:
            return None
        return int(round(v[0] / v[2])), int(round(v[1] / v[2]))

    xs = [p[0] for p in mundo]
    ys = [p[1] for p in mundo]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    passo_y = 1.0 if (y1 - y0) <= 15 else 5.0

    def linhas(inicio, fim, passo):
        valores = []
        v = inicio
        while v <= fim + 1e-9:
            valores.append(v)
            v += passo
        if abs(valores[-1] - fim) > 1e-9:
            valores.append(fim)
        return valores

    for X in linhas(x0, x1, 1.0):
        a, b = proj(X, y0), proj(X, y1)
        if a and b:
            cv2.line(frame, a, b, (255, 255, 0), 1)
    for Y in linhas(y0, y1, passo_y):
        a, b = proj(x0, Y), proj(x1, Y)
        if a and b:
            cv2.line(frame, a, b, (255, 255, 0), 1)
    return frame


def salvar_zonas(caminho, lista_zonas):
    """Grava as zonas no JSON preservando as demais chaves (ex.: homografia)."""
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        dados = {}
    dados["zonas"] = [
        {"nome": z["nome"], "poligono": [list(p) for p in z["poligono"]]} for z in lista_zonas
    ]
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------

def redesenhar(frame_base):
    frame = frame_base.copy()

    if homografia is not None and mostrar_grade:
        desenhar_grade(frame, homografia["H"], homografia["mundo"])

    for i, (x, y) in enumerate(pontos_calibracao):
        cv2.circle(frame, (x, y), 6, (0, 255, 255), -1)
        cv2.putText(frame, f"calib{i+1} ({x},{y})", (x + 8, y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

    for i, (x, y) in enumerate(pontos_chao):
        cv2.circle(frame, (x, y), 6, (0, 200, 255), -1)
        cv2.putText(frame, ROTULOS_CHAO[i], (x + 8, y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)
    if len(pontos_chao) >= 2:
        for i in range(len(pontos_chao) - 1):
            cv2.line(frame, pontos_chao[i], pontos_chao[i + 1], (0, 200, 255), 2)
        if len(pontos_chao) == 4:
            cv2.line(frame, pontos_chao[3], pontos_chao[0], (0, 200, 255), 2)

    for p1, p2, metros in medidas:
        cv2.line(frame, p1, p2, (0, 255, 0), 2)
        meio = ((p1[0] + p2[0]) // 2, (p1[1] + p2[1]) // 2)
        cv2.putText(frame, f"{metros:.2f} m", meio, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    for (x, y) in ponto_medida:
        cv2.circle(frame, (x, y), 5, (0, 255, 0), -1)

    for zona in zonas:
        pts = zona["poligono"]
        for i in range(len(pts)):
            cv2.line(frame, pts[i], pts[(i + 1) % len(pts)], (0, 0, 255), 2)
        cv2.putText(frame, zona["nome"], pts[0], cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    for (x, y) in poligono_atual:
        cv2.circle(frame, (x, y), 5, (255, 0, 255), -1)
        cv2.putText(frame, f"({x},{y})", (x + 8, y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 0, 255), 1)

    texto_modo = f"Modo: {modo or 'nenhum (h=homografia, z=zona, c=simples)'}"
    cv2.putText(frame, texto_modo, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return frame


def clique(event, x, y, flags, param):
    if event != cv2.EVENT_LBUTTONDOWN:
        return

    if modo == "calibracao":
        if len(pontos_calibracao) < 2:
            pontos_calibracao.append((x, y))
            print(f"Ponto de calibração marcado: ({x}, {y})")
        if len(pontos_calibracao) == 2:
            print("2 pontos marcados. Pressione 'q' para finalizar, ou 'r' para refazer.")

    elif modo == "zona":
        poligono_atual.append((x, y))
        print(f"Ponto da zona marcado: ({x}, {y}) — pressione 'n' quando terminar esta zona")

    elif modo == "homografia":
        if len(pontos_chao) < 4:
            pontos_chao.append((x, y))
            print(f"{ROTULOS_CHAO[len(pontos_chao) - 1]} marcado: ({x}, {y})")
        if len(pontos_chao) == 4:
            print("4 pontos marcados. Pressione 'k' para informar as medidas reais, ou 'r' para refazer.")

    elif modo == "validar":
        if homografia is None:
            print("Confirme a homografia ('h' e depois 'k') antes de validar.")
            return
        ponto_medida.append((x, y))
        if len(ponto_medida) == 2:
            metros = medir_no_chao(homografia["H"], ponto_medida[0], ponto_medida[1])
            if metros is None:
                print("Não foi possível medir (ponto fora da região válida da calibração).")
            else:
                medidas.append((ponto_medida[0], ponto_medida[1], metros))
                print(f"Distância calculada no chão: {metros:.2f} m  (compare com a distância real)")
            ponto_medida.clear()


def _pedir_numero(mensagem):
    return float(input(mensagem).strip().replace(",", "."))


def confirmar_homografia():
    """Pede largura/comprimento no terminal e calcula a homografia. Retorna True se deu certo."""
    global homografia, mostrar_grade
    try:
        largura = _pedir_numero("Largura real (P1 -> P2), em metros: ")
        comprimento = _pedir_numero("Comprimento real (P2 -> P3), em metros: ")
        H, mundo = finalizar_homografia(pontos_chao, largura, comprimento)
    except ValueError as e:
        print(f"❌ {e}")
        return False
    homografia = {"H": H, "mundo": mundo, "largura": largura, "comprimento": comprimento}
    mostrar_grade = True
    print("✅ Homografia calculada. A grade de 1 m foi ligada ('g' liga/desliga).")
    print("   Agora valide: tecla 'v' e clique 2 pontos de uma distância que você conheça.")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Vídeo ou imagem para extrair o frame")
    parser.add_argument("--frame", type=int, default=0, help="Índice do frame a extrair (vídeo)")
    parser.add_argument("--saida", default="calibracao_resultado.json")
    args = parser.parse_args()

    global modo, mostrar_grade

    if args.source.lower().endswith((".jpg", ".jpeg", ".png")):
        frame_base = cv2.imread(args.source)
        if frame_base is None:
            raise RuntimeError(f"Não foi possível ler a imagem {args.source}")
    else:
        frame_base = extrair_frame(args.source, args.frame)
    resolucao = (frame_base.shape[1], frame_base.shape[0])

    cv2.namedWindow(JANELA)
    cv2.setMouseCallback(JANELA, clique)

    print(__doc__)
    print(f"Resolução do quadro: {resolucao[0]}x{resolucao[1]}")

    while True:
        cv2.imshow(JANELA, redesenhar(frame_base))
        tecla = cv2.waitKey(20) & 0xFF

        if tecla == ord("h"):
            modo = "homografia"
            pontos_chao.clear()
            print("Modo HOMOGRAFIA: clique P1 perto-esq, P2 perto-dir, P3 longe-dir, P4 longe-esq "
                  "(4 pontos no chão formando um retângulo real).")

        elif tecla == ord("k") and modo == "homografia" and len(pontos_chao) == 4:
            confirmar_homografia()

        elif tecla == ord("v"):
            modo = "validar"
            ponto_medida.clear()
            print("Modo VALIDAR: clique 2 pontos de uma distância real conhecida.")

        elif tecla == ord("g"):
            mostrar_grade = not mostrar_grade

        elif tecla == ord("c"):
            modo = "calibracao"
            pontos_calibracao.clear()
            print("Modo CALIBRAÇÃO SIMPLES: clique 2 pontos com distância real conhecida.")

        elif tecla == ord("z"):
            modo = "zona"
            poligono_atual.clear()
            print("Modo ZONA: clique os pontos do polígono, depois 'n' para fechar.")

        elif tecla == ord("n") and modo == "zona" and len(poligono_atual) >= 3:
            nome = input("Nome desta zona (ex.: cruzamento, faixa_pedestre): ").strip() or f"zona_{len(zonas)+1}"
            zonas.append({"nome": nome, "poligono": list(poligono_atual)})
            print(f"Zona '{nome}' salva com {len(poligono_atual)} pontos.")
            poligono_atual.clear()

        elif tecla == ord("r"):
            pontos_calibracao.clear()
            poligono_atual.clear()
            ponto_medida.clear()
            if homografia is None:
                pontos_chao.clear()
            print("Pontos não confirmados reiniciados (homografia e zonas já fechadas permanecem).")

        elif tecla == ord("q"):
            break

    cv2.destroyAllWindows()

    comando_partes = []

    if homografia is not None:
        salvar_calibracao(
            args.saida, homografia["H"], pontos_chao, homografia["mundo"], resolucao,
            descricao=f"retângulo {homografia['largura']} m x {homografia['comprimento']} m",
        )
        comando_partes.append(f"--calib-arquivo {args.saida}")
        print(f"\n✅ Homografia salva em {args.saida}")
        for p1, p2, metros in medidas:
            print(f"   validação: {p1} -> {p2} = {metros:.2f} m")
    elif len(pontos_calibracao) == 2:
        distancia = input(
            f"Distância real (em metros) entre {pontos_calibracao[0]} e {pontos_calibracao[1]}: "
        ).strip()
        p1 = f"{pontos_calibracao[0][0]},{pontos_calibracao[0][1]}"
        p2 = f"{pontos_calibracao[1][0]},{pontos_calibracao[1][1]}"
        comando_partes.append(f'--calib-p1 "{p1}" --calib-p2 "{p2}" --calib-dist {distancia}')

    if zonas:
        salvar_zonas(args.saida, zonas)
        comando_partes.append(f"--zonas {args.saida}")
        print(f"✅ Zonas salvas em {args.saida}")

    print("\n=== COMANDO PRONTO PARA O main.py ===")
    print(f"python main.py --source {args.source} " + " ".join(comando_partes))


if __name__ == "__main__":
    main()
