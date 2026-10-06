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
    detectar_mudanca_brusca,
    calcular_velocidade_aproximacao,
    esta_parado,
)
from config import (
    LIMIAR_VELOCIDADE_KMH,
    LIMIAR_DISTANCIA_MINIMA_M,
    PESOS_RISCO,
    JANELA_TENDENCIA,
    LIMIAR_MUDANCA_DIRECAO_GRAUS,
    LIMIAR_ACELERACAO_M_S2,
    MIN_DESLOCAMENTO_DIRECAO_M,
    LIMIAR_APROXIMACAO_M_S,
    CLASSES_IGNORADAS_DISTANCIA,
    LIMIAR_PARADO_KMH,
    LIMIAR_PARADO_PX_S,
    MIN_PONTOS_PARADO,
)

# Eventos de transição gerados por calcular_riscos (zona é gerada por
# atualizar_zonas, que conhece o NOME da zona).
EVENTOS_TRANSICAO = (
    "velocidade_elevada",
    "proximidade_perigosa",
    "mudanca_brusca",
    "aproximacao_rapida",
)


def atualizar_historico_e_calcular(objetos, historico, escala, ts, vizinhos=None):
    """
    Atualiza o histórico de posições por track_id e calcula, para cada
    objeto: velocidade estimada e distância até o veículo mais próximo no
    mesmo quadro.

    Ficam FORA do cálculo de distância (nem como alvo, nem como vizinho):
      - pedestres e bicicletas (config.CLASSES_IGNORADAS_DISTANCIA) — ex.:
        manequins detectados como pessoa, bicicleta estacionada;
      - objetos parados (ver risk.esta_parado) — ex.: carro estacionado,
        veículos travados no congestionamento.
    Para esses, a distância fica None.

    historico: dict mutável {track_id: deque de {"x","y","timestamp"}},
        mantido entre chamadas (estado do vídeo inteiro).
    ts: tempo do quadro (ver fonte.timestamp_do_quadro).
    vizinhos: dict opcional, preenchido com {track_id: track_id_do_vizinho_mais_proximo}
        (usado por calcular_tendencias para a aproximação rápida).

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

    elegiveis = [obj for obj in objetos if objeto_entra_na_distancia(obj, historico, escala)]
    ids_elegiveis = {id(obj) for obj in elegiveis}

    distancias = {}
    for obj_a in objetos:
        if id(obj_a) not in ids_elegiveis:
            distancias[obj_a["track_id"]] = None
            continue
        menor, vizinho = None, None
        for obj_b in elegiveis:
            if obj_b is obj_a:
                continue
            d = calcular_distancia(obj_a, obj_b, escala)
            if menor is None or d < menor:
                menor, vizinho = d, obj_b["track_id"]
        distancias[obj_a["track_id"]] = menor
        if vizinhos is not None and obj_a["track_id"] is not None:
            vizinhos[obj_a["track_id"]] = vizinho

    return velocidades, distancias


def objeto_entra_na_distancia(obj, historico, escala):
    """True se o objeto deve participar do cálculo de distância (ver acima)."""
    if obj.get("vehicle_type") in CLASSES_IGNORADAS_DISTANCIA:
        return False
    tid = obj["track_id"]
    if tid is None:
        return True  # sem histórico não há como dizer que está parado
    return not esta_parado(
        list(historico[tid]), escala, LIMIAR_PARADO_KMH, LIMIAR_PARADO_PX_S, MIN_PONTOS_PARADO
    )


def calcular_tendencias(objetos, historico, distancias, vizinhos, historico_distancias, escala, ts):
    """
    Calcula, por track_id, os indicadores que dependem da evolução ao longo
    dos quadros: mudança brusca (trajetória/velocidade) e velocidade de
    aproximação ao vizinho mais próximo.

    historico_distancias: dict mutável {track_id: deque/lista de
        {"distancia","vizinho","timestamp"}}, mantido entre chamadas.

    Só funciona com calibração (escala) — em pixels os limiares em metros
    não fazem sentido; sem calibração devolve sem tendência para todos.

    Retorna {track_id: {"mudanca_brusca": bool, "velocidade_aproximacao": m/s|None}}
    """
    tendencias = {}
    for obj in objetos:
        tid = obj["track_id"]
        if tid is None:
            continue
        if escala is None:
            tendencias[tid] = {"mudanca_brusca": False, "velocidade_aproximacao": None}
            continue

        brusca = detectar_mudanca_brusca(
            list(historico[tid]), escala,
            LIMIAR_MUDANCA_DIRECAO_GRAUS, LIMIAR_ACELERACAO_M_S2,
            MIN_DESLOCAMENTO_DIRECAO_M, JANELA_TENDENCIA,
        )

        dist = distancias.get(tid)
        hist_d = historico_distancias[tid]
        if dist is None:
            hist_d.clear()  # sem vizinho válido: a sequência é interrompida
            aproximacao = None
        else:
            hist_d.append({"distancia": dist, "vizinho": vizinhos.get(tid), "timestamp": ts})
            aproximacao = calcular_velocidade_aproximacao(list(hist_d), JANELA_TENDENCIA)

        tendencias[tid] = {"mudanca_brusca": brusca, "velocidade_aproximacao": aproximacao}
    return tendencias


def atualizar_zonas(objetos, zonas, zona_por_track, ts=None):
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
    ts = ts if ts is not None else datetime.now()

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
                "timestamp": ts,
                "severity": None,
                "speed_estimated": None,  # preenchido pelo chamador, que já tem velocidades
                "distance": None,
                "zona": zona_nome,
            })
        zona_por_track[tid] = zona_nome

    return zonas_atuais, entradas


def calcular_riscos(objetos, velocidades, distancias, zonas_atuais, estado_condicoes,
                    tendencias=None, ts=None):
    """
    Para cada objeto rastreado: detecta as condições de risco ativas AGORA
    (velocidade elevada, proximidade perigosa, zona de risco, mudança brusca,
    aproximação rápida), calcula o score/nível combinado, e gera eventos
    discretos de TRANSIÇÃO (mesmo princípio usado em atualizar_zonas: um
    evento só é gerado quando a condição começa, não a cada quadro que ela
    permanece ativa).

    estado_condicoes: dict mutável {track_id: {tipo_evento: bool}}, mantido
        entre chamadas.
    tendencias: saída de calcular_tendencias (opcional).
    ts: tempo do quadro (padrão: datetime.now()).

    Retorna:
        analises: lista de dicts prontos para db.salvar_analises_risco
            (um por track_id rastreado neste frame).
        eventos_transicao: lista de dicts prontos para db.salvar_eventos
            (só para quem ACABOU de entrar em uma das condições de
            EVENTOS_TRANSICAO).
    """
    analises = []
    eventos_transicao = []
    ts = ts if ts is not None else datetime.now()
    tendencias = tendencias or {}

    for obj in objetos:
        tid = obj["track_id"]
        if tid is None:
            continue

        velocidade = velocidades.get(tid)
        distancia = distancias.get(tid)
        zona = zonas_atuais.get(tid)
        tendencia = tendencias.get(tid, {})

        eventos_ativos = detectar_eventos_ativos(
            velocidade, distancia, zona,
            LIMIAR_VELOCIDADE_KMH, LIMIAR_DISTANCIA_MINIMA_M,
            mudanca_brusca=tendencia.get("mudanca_brusca", False),
            velocidade_aproximacao=tendencia.get("velocidade_aproximacao"),
            limiar_aproximacao=LIMIAR_APROXIMACAO_M_S,
        )
        score, nivel = calcular_score(eventos_ativos, PESOS_RISCO)

        analises.append({
            "track_id": tid,
            "timestamp": ts,
            "risk_score": score,
            "risk_level": nivel,
        })

        # transições (debounce) — zona já é tratada em atualizar_zonas,
        # que sabe o NOME da zona
        estado_anterior = estado_condicoes.setdefault(tid, {})
        for tipo_evento in EVENTOS_TRANSICAO:
            ativo_agora = tipo_evento in eventos_ativos
            if ativo_agora and not estado_anterior.get(tipo_evento, False):
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