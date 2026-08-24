"""
Calibração pixel -> metros.

Sem calibrar a câmera, velocidade e distância só existem em pixels,
o que não tem significado físico. Este módulo converte uma calibração
simples (dois pontos na imagem + distância real entre eles) em um
fator de escala (metros por pixel).

Isso é uma aproximação: assume que a escala é constante em toda a
cena, o que só é razoável para câmeras com pouca perspectiva/inclinação.
Essa limitação deve ser citada no TCC (seção 10 do documento do projeto).
"""

import math


def calcular_escala(ponto1, ponto2, distancia_real_metros):
    """
    ponto1, ponto2: tuplas (x, y) em pixels, marcando dois pontos na imagem
        cuja distância real no mundo é conhecida (ex.: duas faixas da via).
    distancia_real_metros: distância real entre esses dois pontos, em metros.

    Retorna metros_por_pixel (float).
    """
    dist_px = math.dist(ponto1, ponto2)
    if dist_px == 0:
        raise ValueError("Os dois pontos de calibração não podem ser iguais.")
    return distancia_real_metros / dist_px


def parse_calibracao(p1_str, p2_str, distancia_str):
    """
    Converte os argumentos de linha de comando (strings "x,y") em uma escala.
    Retorna None se qualquer um dos três não for informado (sem calibração).
    """
    if not (p1_str and p2_str and distancia_str):
        return None
    x1, y1 = map(float, p1_str.split(","))
    x2, y2 = map(float, p2_str.split(","))
    distancia = float(distancia_str)
    return calcular_escala((x1, y1), (x2, y2), distancia)
