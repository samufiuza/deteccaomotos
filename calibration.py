"""
Calibração pixel -> metros.

Sem calibrar a câmera, velocidade e distância só existem em pixels,
o que não tem significado físico. Este módulo converte uma calibração
simples (dois pontos na imagem + distância real entre eles) em um
fator de escala (metros por pixel).

Isso é uma aproximação: assume que a escala é constante em toda a
cena, o que só é razoável para câmeras com pouca perspectiva/inclinação.
Essa limitação deve ser citada no TCC (seção 10 do documento do projeto).

Para câmeras inclinadas (a maioria das câmeras urbanas), este módulo também
oferece a calibração por HOMOGRAFIA: 4 pontos do chão, com coordenadas reais
em metros, definem uma transformação (matriz 3x3) da imagem para o plano do
chão. Com ela, a escala varia corretamente com a profundidade (um objeto
longe vale mais metros por pixel do que um perto), o que o fator único
não consegue representar.
"""

import json
import math

import numpy as np


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


# =====================================================================
# Calibração por homografia (plano do chão)
# =====================================================================

def calcular_homografia(pontos_imagem, pontos_mundo):
    """
    Calcula a matriz 3x3 H que leva pontos da imagem (pixels) para o plano do
    chão (metros), a partir de 4 correspondências.

    pontos_imagem: 4 pontos (x, y) em pixels, sobre o CHÃO (não em objetos altos).
    pontos_mundo: os mesmos 4 pontos, em metros, num sistema de coordenadas
        planar qualquer (ex.: retângulo (0,0), (L,0), (L,C), (0,C)).

    Retorna H como numpy array 3x3, normalizada com H[2,2] = 1.
    Levanta ValueError se os pontos forem degenerados (ex.: três colineares).
    """
    if len(pontos_imagem) != 4 or len(pontos_mundo) != 4:
        raise ValueError("São necessários exatamente 4 pontos na imagem e 4 no mundo.")

    A = []
    b = []
    for (x, y), (X, Y) in zip(pontos_imagem, pontos_mundo):
        A.append([x, y, 1, 0, 0, 0, -X * x, -X * y])
        b.append(X)
        A.append([0, 0, 0, x, y, 1, -Y * x, -Y * y])
        b.append(Y)

    try:
        h = np.linalg.solve(np.array(A, dtype=float), np.array(b, dtype=float))
    except np.linalg.LinAlgError as e:
        raise ValueError("Pontos de calibração degenerados (colineares ou repetidos).") from e

    H = np.append(h, 1.0).reshape(3, 3)
    if not np.all(np.isfinite(H)) or abs(np.linalg.det(H)) < 1e-12:
        raise ValueError("Pontos de calibração degenerados (matriz não inversível).")
    return H


def aplicar_homografia(H, x, y):
    """
    Converte um ponto da imagem (x, y) em pixels para o plano do chão (X, Y)
    em metros. Retorna None se o ponto cair no infinito (denominador ~ 0,
    por exemplo, em cima do horizonte).
    """
    v = np.asarray(H, dtype=float) @ np.array([x, y, 1.0])
    if abs(v[2]) < 1e-12:
        return None
    return float(v[0] / v[2]), float(v[1] / v[2])


def distancia_no_chao(H, ponto_a, ponto_b):
    """Distância em metros entre dois pontos da imagem (pixels), medida no plano do chão."""
    a = aplicar_homografia(H, *ponto_a)
    b = aplicar_homografia(H, *ponto_b)
    if a is None or b is None:
        return None
    return math.dist(a, b)


def reescalar_homografia(H, resolucao_calibracao, resolucao_atual):
    """
    Ajusta H quando o vídeo atual tem resolução diferente da imagem usada na
    calibração (ex.: calibrou em 1280x720 e o vídeo está em 1920x1080).

    resolucao_*: (largura, altura). Levanta ValueError se a proporção
    (largura/altura) diferir mais de 2% — nesse caso a imagem provavelmente
    foi cortada/esticada e é preciso recalibrar.
    """
    w0, h0 = resolucao_calibracao
    w1, h1 = resolucao_atual
    if abs((w1 / h1) / (w0 / h0) - 1.0) > 0.02:
        raise ValueError(
            f"Proporção da imagem mudou ({w0}x{h0} na calibração, {w1}x{h1} agora). Recalibre."
        )
    sx, sy = w1 / w0, h1 / h0
    S_inv = np.diag([1.0 / sx, 1.0 / sy, 1.0])  # pixel atual -> pixel da calibração
    return np.asarray(H, dtype=float) @ S_inv


def projetar_objetos(objetos, H):
    """
    Para cada objeto detectado (dict com "bbox" = (x1, y1, x2, y2)), calcula a
    posição no plano do chão em metros e grava em obj["mx"], obj["my"].

    O ponto usado é o centro da base da caixa (onde o veículo toca o chão),
    porque a homografia só vale para pontos NO CHÃO — o centro da caixa está
    no ar e distorceria as medidas. Se a projeção falhar, mx e my ficam None.
    """
    for obj in objetos:
        x1, y1, x2, y2 = obj["bbox"]
        p = aplicar_homografia(H, (x1 + x2) / 2.0, y2)
        obj["mx"], obj["my"] = (p if p is not None else (None, None))
    return objetos


def salvar_calibracao(caminho, H, pontos_imagem, pontos_mundo, resolucao, descricao=""):
    """
    Salva/atualiza o arquivo JSON de calibração, na chave "homografia".
    Se o arquivo já existir (ex.: com zonas), preserva as demais chaves.
    """
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        dados = {}

    dados["homografia"] = {
        "matriz": np.asarray(H, dtype=float).tolist(),
        "pontos_imagem": [list(map(float, p)) for p in pontos_imagem],
        "pontos_mundo_m": [list(map(float, p)) for p in pontos_mundo],
        "resolucao": [int(resolucao[0]), int(resolucao[1])],
        "descricao": descricao,
    }
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)


def carregar_calibracao(caminho):
    """
    Lê a chave "homografia" de um arquivo JSON de calibração.
    Retorna (H: numpy 3x3, resolucao: (largura, altura)).
    Levanta ValueError se o arquivo não tiver calibração por homografia.
    """
    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)
    if "homografia" not in dados:
        raise ValueError(f"{caminho} não contém a chave 'homografia'. Rode a ferramenta_calibracao (tecla h).")
    bloco = dados["homografia"]
    H = np.array(bloco["matriz"], dtype=float)
    if H.shape != (3, 3):
        raise ValueError("Matriz de homografia inválida (esperado 3x3).")
    return H, tuple(bloco["resolucao"])
