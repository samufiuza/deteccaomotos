"""
Análise de risco.

Velocidade, distância e zona: implementadas.
Tendência (mudanca_brusca, aproximacao_rapida): implementadas — analisam a
evolução nos últimos quadros, não só o quadro atual.
Score: implementado (combina os eventos ativos no quadro atual).
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


def detectar_eventos_ativos(velocidade, distancia, zona, limiar_velocidade, limiar_distancia,
                            mudanca_brusca=False, velocidade_aproximacao=None,
                            limiar_aproximacao=None):
    """
    Verifica, para os valores ATUAIS de um track_id, quais condições de
    risco estão ativas agora.

    velocidade: km/h estimado, ou None se não calibrado.
    distancia: metros até o veículo mais próximo, ou None.
    zona: nome da zona de risco em que o veículo está, ou None.
    mudanca_brusca: bool já calculado por detectar_mudanca_brusca.
    velocidade_aproximacao: m/s com que a distância ao vizinho diminui
        (ver calcular_velocidade_aproximacao), ou None.
    limiar_aproximacao: m/s a partir do qual vira "aproximacao_rapida".

    Retorna uma lista de strings (nomes de eventos ativos agora), entre:
    "velocidade_elevada", "proximidade_perigosa", "zona_risco",
    "mudanca_brusca", "aproximacao_rapida".
    """
    eventos = []

    if velocidade is not None and velocidade >= limiar_velocidade:
        eventos.append("velocidade_elevada")

    if distancia is not None and distancia <= limiar_distancia:
        eventos.append("proximidade_perigosa")

    if zona is not None:
        eventos.append("zona_risco")

    if mudanca_brusca:
        eventos.append("mudanca_brusca")

    if (velocidade_aproximacao is not None and limiar_aproximacao is not None
            and velocidade_aproximacao >= limiar_aproximacao):
        eventos.append("aproximacao_rapida")

    return eventos


def detectar_mudanca_brusca(historico_posicoes, escala_px_para_metros, limiar_angulo_graus,
                            limiar_aceleracao_m_s2, min_deslocamento_m, janela=6):
    """
    Detecta mudança brusca de trajetória OU de velocidade nos últimos
    `janela` pontos de um track_id.

    A janela é dividida em duas metades (A = início->meio, B = meio->fim):
      - direção: ângulo entre os vetores A e B >= limiar_angulo_graus
        (só avaliado se as duas metades andaram pelo menos min_deslocamento_m,
        para não confundir o tremor da bounding box com uma curva);
      - velocidade: |vel_B - vel_A| / tempo entre os centros das metades
        >= limiar_aceleracao_m_s2 (freada ou arrancada brusca).

    Retorna False se não houver calibração ou histórico suficiente (< 3 pontos).
    """
    if escala_px_para_metros is None:
        return False
    pontos = historico_posicoes[-janela:]
    if len(pontos) < 3:
        return False

    meio = len(pontos) // 2
    a0, a1, b1 = pontos[0], pontos[meio], pontos[-1]
    dt_a = (a1["timestamp"] - a0["timestamp"]).total_seconds()
    dt_b = (b1["timestamp"] - a1["timestamp"]).total_seconds()
    if dt_a <= 0 or dt_b <= 0:
        return False

    va = ((a1["x"] - a0["x"]) * escala_px_para_metros, (a1["y"] - a0["y"]) * escala_px_para_metros)
    vb = ((b1["x"] - a1["x"]) * escala_px_para_metros, (b1["y"] - a1["y"]) * escala_px_para_metros)
    desl_a, desl_b = math.hypot(*va), math.hypot(*vb)

    # 1) mudança de direção
    if desl_a >= min_deslocamento_m and desl_b >= min_deslocamento_m:
        cos_ang = (va[0] * vb[0] + va[1] * vb[1]) / (desl_a * desl_b)
        angulo = math.degrees(math.acos(max(-1.0, min(1.0, cos_ang))))
        if angulo >= limiar_angulo_graus:
            return True

    # 2) variação brusca de velocidade (freada/arrancada)
    vel_a, vel_b = desl_a / dt_a, desl_b / dt_b
    dt_centros = (dt_a + dt_b) / 2
    aceleracao = abs(vel_b - vel_a) / dt_centros
    return aceleracao >= limiar_aceleracao_m_s2


def calcular_velocidade_aproximacao(historico_distancias, janela=6):
    """
    historico_distancias: lista de dicts {"distancia": metros, "vizinho": track_id,
        "timestamp": datetime}, em ordem cronológica, de um mesmo track_id.

    Usa só a sequência final em que o vizinho mais próximo é o MESMO veículo
    (se o vizinho mudou, a "queda" de distância é troca de referência, não
    aproximação real).

    Retorna m/s com que a distância diminui (positivo = aproximando,
    negativo = afastando), ou None se não houver dados suficientes.
    """
    if not historico_distancias:
        return None
    vizinho_atual = historico_distancias[-1]["vizinho"]
    trecho = []
    for item in reversed(historico_distancias):
        if item["vizinho"] != vizinho_atual or item["distancia"] is None:
            break
        trecho.append(item)
        if len(trecho) == janela:
            break
    if len(trecho) < 2:
        return None
    trecho.reverse()
    dt = (trecho[-1]["timestamp"] - trecho[0]["timestamp"]).total_seconds()
    if dt <= 0:
        return None
    return (trecho[0]["distancia"] - trecho[-1]["distancia"]) / dt


def esta_parado(historico_posicoes, escala_px_para_metros, limiar_kmh, limiar_px_s, min_pontos):
    """
    Diz se um objeto está parado, olhando seu histórico recente.

    Com calibração: velocidade (km/h) abaixo de limiar_kmh.
    Sem calibração: deslocamento em pixels/segundo abaixo de limiar_px_s.
    Com menos de min_pontos no histórico retorna False (ainda não dá para
    afirmar — o objeto acabou de aparecer).
    """
    if len(historico_posicoes) < min_pontos:
        return False
    pontos = historico_posicoes[-min_pontos:]
    if escala_px_para_metros is not None:
        vel = calcular_velocidade(pontos, escala_px_para_metros, janela=min_pontos)
        return vel is not None and vel < limiar_kmh
    inicio, fim = pontos[0], pontos[-1]
    dt = (fim["timestamp"] - inicio["timestamp"]).total_seconds()
    if dt <= 0:
        return False
    px_s = math.dist((inicio["x"], inicio["y"]), (fim["x"], fim["y"])) / dt
    return px_s < limiar_px_s


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
