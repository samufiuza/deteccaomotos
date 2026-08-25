"""
Análise de risco.

Velocidade e distância: implementadas (etapa atual).
Zona de risco e score: ainda stubs, para as próximas etapas.
"""

import math


def calcular_velocidade(historico_posicoes, escala_px_para_metros=None, janela=5):
    """
    historico_posicoes: lista de dicts {"x": float, "y": float, "timestamp": datetime},
        do mesmo track_id, em ordem cronológica (mais antigo primeiro).
    escala_px_para_metros: fator de calibração (ver calibration.py). Se None,
        a velocidade não pode ser convertida para km/h de forma confiável.
    janela: quantos pontos recentes usar para suavizar o cálculo (reduz ruído
        de detecção frame a frame).

    Retorna velocidade estimada em km/h (float), ou None se:
        - não houver calibração (escala_px_para_metros é None);
        - não houver histórico suficiente (menos de 2 pontos).

    Importante (documentar no TCC): isso é uma ESTIMATIVA. Sem calibração
    validada da câmera, não deve ser tratada como velocidade real do veículo.
    """
    if escala_px_para_metros is None:
        return None

    pontos = historico_posicoes[-janela:]
    if len(pontos) < 2:
        return None

    inicio, fim = pontos[0], pontos[-1]
    dt = (fim["timestamp"] - inicio["timestamp"]).total_seconds()
    if dt <= 0:
        return None

    dist_px = math.dist((inicio["x"], inicio["y"]), (fim["x"], fim["y"]))
    dist_m = dist_px * escala_px_para_metros

    velocidade_m_s = dist_m / dt
    velocidade_kmh = velocidade_m_s * 3.6
    return velocidade_kmh


def calcular_distancia(pos_a, pos_b, escala_px_para_metros=None):
    """
    pos_a, pos_b: dicts {"x": float, "y": float} (centros de bounding box).

    Retorna a distância em metros, se houver calibração, ou em pixels
    (com uma nota de que não é uma unidade real) caso contrário.
    """
    dist_px = math.dist((pos_a["x"], pos_a["y"]), (pos_b["x"], pos_b["y"]))
    if escala_px_para_metros is not None:
        return dist_px * escala_px_para_metros
    return dist_px  # sem calibração: valor em pixels, não comparável entre vídeos


def checar_zona(x, y, zonas):
    """
    zonas: lista de dicts {"nome": str, "poligono": [(x1,y1), (x2,y2), ...]}
        representando as zonas de risco definidas para o vídeo (ver config/zonas.json).

    Retorna o nome da primeira zona em que o ponto (x, y) está, ou None se
    não estiver em nenhuma. Se zonas se sobrepuserem, a ordem da lista decide
    a prioridade (a primeira que contiver o ponto vence).
    """
    for zona in zonas:
        if _ponto_dentro_poligono(x, y, zona["poligono"]):
            return zona["nome"]
    return None


def _ponto_dentro_poligono(x, y, poligono):
    """
    Algoritmo ray casting: conta quantas vezes uma semirreta horizontal a
    partir do ponto cruza as arestas do polígono. Número ímpar de cruzamentos
    = ponto dentro.

    poligono: lista de (x, y) em ordem (sentido horário ou anti-horário,
        não importa). Precisa de pelo menos 3 pontos.

    Nota: pontos exatamente sobre uma aresta têm comportamento indefinido
    (podem contar como dentro ou fora, dependendo do arredondamento) — não é
    um problema prático aqui, já que estamos testando o centro de bounding
    boxes, não pontos desenhados manualmente sobre a linha da zona.
    """
    dentro = False
    n = len(poligono)
    x1, y1 = poligono[0]
    for i in range(1, n + 1):
        x2, y2 = poligono[i % n]
        if y > min(y1, y2):
            if y <= max(y1, y2):
                if x <= max(x1, x2):
                    if y1 != y2:
                        x_intersecao = (y - y1) * (x2 - x1) / (y2 - y1) + x1
                    if x1 == x2 or x <= x_intersecao:
                        dentro = not dentro
        x1, y1 = x2, y2
    return dentro


def calcular_score(eventos):
    """
    eventos: lista de strings com os tipos de evento detectados para um track_id
        (ex.: "velocidade_elevada", "proximidade_perigosa", "zona_risco").

    Retorna (score: int, nivel: str) conforme a tabela de pesos definida no TCC.
    """
    # TODO: implementar na etapa "Score" do MVP
    return 0, "indefinido"
