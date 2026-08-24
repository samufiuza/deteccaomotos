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
    zonas: lista de polígonos (cada um uma lista de pontos (x, y)) representando
    zonas de risco definidas na configuração do projeto.

    Retorna o nome da zona em que o ponto está, ou None.
    """
    # TODO: implementar na etapa "Zona de risco" do MVP (point-in-polygon)
    return None


def calcular_score(eventos):
    """
    eventos: lista de strings com os tipos de evento detectados para um track_id
        (ex.: "velocidade_elevada", "proximidade_perigosa", "zona_risco").

    Retorna (score: int, nivel: str) conforme a tabela de pesos definida no TCC.
    """
    # TODO: implementar na etapa "Score" do MVP
    return 0, "indefinido"
