"""
Análise de risco.

Velocidade, distância e zona: implementadas.
Score: implementado (combina os eventos ativos no frame atual).
"mudanca_brusca" e "aproximacao_rapida" ainda não são detectados — exigem
análise de tendência ao longo do tempo, não só do frame atual.
"""

import math

from config import NIVEIS_RISCO


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


def detectar_eventos_ativos(velocidade, distancia, zona, limiar_velocidade, limiar_distancia):
    """
    Verifica, para os valores ATUAIS (de um frame) de um track_id, quais
    condições de risco estão ativas agora.

    velocidade: km/h estimado, ou None se não calibrado.
    distancia: metros até o veículo mais próximo, ou None (se calibrado em
        metros — se vier em pixels por falta de calibração, é ignorada aqui,
        pois pixels não são comparáveis ao limiar em metros).
    zona: nome da zona de risco em que o veículo está, ou None.

    Retorna uma lista de strings (nomes de eventos ativos agora), entre:
    "velocidade_elevada", "proximidade_perigosa", "zona_risco".

    Nota: "mudanca_brusca" e "aproximacao_rapida" não são detectados aqui —
    exigem histórico/tendência, não só o frame atual (próxima iteração).
    """
    eventos = []

    if velocidade is not None and velocidade >= limiar_velocidade:
        eventos.append("velocidade_elevada")

    if distancia is not None and distancia <= limiar_distancia:
        eventos.append("proximidade_perigosa")

    if zona is not None:
        eventos.append("zona_risco")

    return eventos


def calcular_score(eventos_ativos, pesos):
    """
    eventos_ativos: lista de strings com os tipos de evento ativos AGORA
        para um track_id (ver detectar_eventos_ativos). Duplicatas são
        ignoradas — cada tipo de evento conta seu peso uma única vez.
    pesos: dict {tipo_evento: peso_inteiro} (ver config.PESOS_RISCO).

    Retorna (score: int 0-100, nivel: str "baixo"|"medio"|"alto").

    A pontuação é a soma dos pesos dos tipos de evento distintos presentes,
    limitada a 100. É um parâmetro experimental do projeto, não uma verdade
    absoluta — os pesos devem ser justificados/calibrados com os testes reais
    (ver seção de avaliação experimental do TCC).
    """
    tipos_unicos = set(eventos_ativos)
    score = sum(pesos.get(tipo, 0) for tipo in tipos_unicos)
    score = min(score, 100)

    nivel = "baixo"
    for minimo, maximo, nome in NIVEIS_RISCO:
        if minimo <= score <= maximo:
            nivel = nome
            break

    return score, nivel
