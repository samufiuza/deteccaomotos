"""
Lógica de estado do pipeline — histórico de posições, zonas de risco e score.

Fica separado de main.py de propósito: não depende de ultralytics nem de
psycopg2, então dá para testar (e importar) sem precisar instalar essas
dependências pesadas.
"""

from datetime import datetime

from risk import (
    calcular_velocidade,
    calcular_distancia,
    checar_zona,
    detectar_eventos_ativos,
    calcular_score,
)
from config import LIMIAR_VELOCIDADE_KMH, LIMIAR_DISTANCIA_MINIMA_M, PESOS_RISCO


def atualizar_historico_e_calcular(objetos, historico, escala, ts):
    """
    Atualiza o histórico de posições por track_id e calcula, para cada
    objeto: velocidade estimada e distância até o veículo mais próximo no
    mesmo frame.

    historico: dict mutável {track_id: deque de {"x","y","timestamp"}},
        mantido entre chamadas (estado do vídeo inteiro).

    Retorna (velocidades: {track_id: km/h|None}, distancias: {track_id: metros|pixels|None})
    """
    for obj in objetos:
        if obj["track_id"] is None:
            continue
        historico[obj["track_id"]].append({"x": obj["x"], "y": obj["y"], "timestamp": ts})

    velocidades = {}
    for obj in objetos:
        tid = obj["track_id"]
        if tid is None:
            velocidades[tid] = None
            continue
        velocidades[tid] = calcular_velocidade(list(historico[tid]), escala)

    distancias = {}
    for i, obj_a in enumerate(objetos):
        menor = None
        for j, obj_b in enumerate(objetos):
            if i == j:
                continue
            d = calcular_distancia(obj_a, obj_b, escala)
            if menor is None or d < menor:
                menor = d
        distancias[obj_a["track_id"]] = menor

    return velocidades, distancias


def atualizar_zonas(objetos, zonas, zona_por_track):
    """
    Calcula a zona atual de cada objeto e detecta TRANSIÇÕES de entrada
    (para não gerar um evento repetido a cada frame que o veículo passa
    dentro da mesma zona; reentradas após sair, sim, geram novo evento).

    zona_por_track: dict mutável {track_id: nome_da_zona_ou_None}, mantido
        entre chamadas (estado do vídeo inteiro).

    Retorna (zonas_atuais: {track_id: nome|None}, entradas: lista de dicts
        prontos para db.salvar_eventos, só para quem ACABOU de entrar em uma zona).
    """
    zonas_atuais = {}
    entradas = []

    for obj in objetos:
        tid = obj["track_id"]
        if tid is None:
            continue
        zona_nome = checar_zona(obj["x"], obj["y"], zonas)
        zonas_atuais[tid] = zona_nome

        zona_anterior = zona_por_track.get(tid)
        if zona_nome is not None and zona_nome != zona_anterior:
            entradas.append({
                "track_id": tid,
                "event_type": "entrada_zona_risco",
                "timestamp": datetime.now(),
                "severity": None,
                "speed_estimated": None,  # preenchido pelo chamador, que já tem velocidades
                "distance": None,
                "zona": zona_nome,
            })
        zona_por_track[tid] = zona_nome

    return zonas_atuais, entradas


def calcular_riscos(objetos, velocidades, distancias, zonas_atuais, estado_condicoes):
    """
    Para cada objeto rastreado: detecta as condições de risco ativas AGORA
    (velocidade elevada, proximidade perigosa, zona de risco), calcula o
    score/nível combinado, e gera eventos discretos de TRANSIÇÃO para
    velocidade/proximidade (mesmo princípio usado em atualizar_zonas: um
    evento só é gerado quando a condição começa, não a cada frame que ela
    permanece ativa).

    estado_condicoes: dict mutável {track_id: {"velocidade_elevada": bool,
        "proximidade_perigosa": bool}}, mantido entre chamadas.

    Retorna:
        analises: lista de dicts prontos para db.salvar_analises_risco
            (um por track_id rastreado neste frame).
        eventos_transicao: lista de dicts prontos para db.salvar_eventos
            (só para quem ACABOU de entrar em condição de velocidade
            elevada ou proximidade perigosa).
    """
    analises = []
    eventos_transicao = []
    ts = datetime.now()

    for obj in objetos:
        tid = obj["track_id"]
        if tid is None:
            continue

        velocidade = velocidades.get(tid)
        distancia = distancias.get(tid)
        zona = zonas_atuais.get(tid)

        eventos_ativos = detectar_eventos_ativos(
            velocidade, distancia, zona,
            LIMIAR_VELOCIDADE_KMH, LIMIAR_DISTANCIA_MINIMA_M,
        )
        score, nivel = calcular_score(eventos_ativos, PESOS_RISCO)

        analises.append({
            "track_id": tid,
            "timestamp": ts,
            "risk_score": score,
            "risk_level": nivel,
        })

        # transições (debounce) só para velocidade e proximidade — zona já
        # é tratada em atualizar_zonas, que sabe o NOME da zona
        estado_anterior = estado_condicoes.setdefault(
            tid, {"velocidade_elevada": False, "proximidade_perigosa": False}
        )
        for tipo_evento in ("velocidade_elevada", "proximidade_perigosa"):
            ativo_agora = tipo_evento in eventos_ativos
            if ativo_agora and not estado_anterior[tipo_evento]:
                eventos_transicao.append({
                    "track_id": tid,
                    "event_type": tipo_evento,
                    "timestamp": ts,
                    "severity": nivel,
                    "speed_estimated": velocidade,
                    "distance": distancia,
                    "zona": zona,
                })
            estado_anterior[tipo_evento] = ativo_agora

    return analises, eventos_transicao


def atualizar_presenca_motos(objetos, contagem_frames, min_frames):
    """
    Conta em quantos frames cada track_id de moto já apareceu, e retorna o
    conjunto de IDs que já atingiram o mínimo de frames para serem
    considerados "moto confirmada" — e não ruído (falso positivo isolado,
    ou troca de ID que dura só 1-2 frames).

    contagem_frames: dict mutável {track_id: int}, mantido entre chamadas
        (estado do vídeo inteiro).
    min_frames: ver config.MIN_FRAMES_PRESENCA_MOTO.

    Retorna o conjunto de track_ids confirmados até agora (recalculado a
    cada chamada a partir de contagem_frames, então sempre reflete o estado
    mais atual mesmo se chamado fora de ordem).
    """
    for obj in objetos:
        if obj["vehicle_type"] == "motorcycle" and obj["track_id"] is not None:
            contagem_frames[obj["track_id"]] += 1

    return {tid for tid, contagem in contagem_frames.items() if contagem >= min_frames}