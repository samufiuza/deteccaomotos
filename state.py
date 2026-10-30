"""
Lógica de estado do pipeline — histórico de posições, zonas de risco e score.

Fica separado de main.py de propósito: não depende de ultralytics nem de
psycopg2, então dá para testar (e importar) sem precisar instalar essas
dependências pesadas.
"""

from datetime import datetime

from predicao import (
    estimar_velocidade_vetorial,
    menor_distancia_prevista,
    posicao_atual_m,
)
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
    RISCO_SOMENTE_ALVO,
    COOLDOWN_EVENTO_S,
    PREDICAO_ATIVA,
    HORIZONTE_PREDICAO_S,
    PREDICAO_JANELA_PONTOS,
    PREDICAO_MIN_PONTOS,
    LIMIAR_PARADO_KMH,
    LIMIAR_PARADO_PX_S,
    MIN_PONTOS_PARADO,
    MODOS_PARADOS,
    PARADOS_NA_DISTANCIA,
)

# Eventos de transição gerados por calcular_riscos (zona é gerada por
# atualizar_zonas, que conhece o NOME da zona).
EVENTOS_TRANSICAO = (
    "velocidade_elevada",
    "proximidade_perigosa",
    "mudanca_brusca",
    "aproximacao_rapida",
    "proximidade_prevista",   # predição; não entra no score (ver config, PREDICAO_*)
)


def atualizar_historico_e_calcular(objetos, historico, escala, ts, vizinhos=None,
                                    usar_plano_chao=False, parados_na_distancia=None):
    """
    Atualiza o histórico de posições por track_id e calcula, para cada
    objeto: velocidade estimada e distância até o veículo mais próximo no
    mesmo quadro.

    Ficam FORA do cálculo de distância (nem como alvo, nem como vizinho):
      - pedestres e bicicletas (config.CLASSES_IGNORADAS_DISTANCIA) — ex.:
        manequins detectados como pessoa, bicicleta estacionada.
    Objetos PARADOS (ver risk.esta_parado — ex.: carro estacionado, veículos
    travados no congestionamento) dependem de `parados_na_distancia`:
      - "alvo_e_vizinho" (padrão): ficam fora nos dois papéis;
      - "so_alvo": não geram distância para si, mas continuam valendo como
        vizinho de quem está em movimento.
    Para quem não é alvo, a distância fica None.

    historico: dict mutável {track_id: deque de {"x","y","timestamp"}},
        mantido entre chamadas (estado do vídeo inteiro).
    ts: tempo do quadro (ver fonte.timestamp_do_quadro).
    vizinhos: dict opcional, preenchido com {track_id: track_id_do_vizinho_mais_proximo}
        (usado por calcular_tendencias para a aproximação rápida).
    parados_na_distancia: "alvo_e_vizinho" ou "so_alvo" (ver acima). None usa
        config.PARADOS_NA_DISTANCIA. Valor inválido levanta ValueError.
    usar_plano_chao: se True (calibração por homografia, ver calibration.py), as
        posições vêm de obj["mx"], obj["my"] — metros no plano do chão, no ponto
        de contato do veículo — e `escala` é ignorada (as posições já estão em
        metros, equivale a escala 1,0). O histórico passa a guardar metros, então
        quem o consome depois (calcular_tendencias) deve receber escala 1,0.
        Objetos sem projeção (mx/my None) ficam fora de todos os cálculos:
        velocidade e distância None para eles.

    Retorna (velocidades: {track_id: km/h|None}, distancias: {track_id: metros|pixels|None})
    """
    modo = PARADOS_NA_DISTANCIA if parados_na_distancia is None else parados_na_distancia
    if modo not in MODOS_PARADOS:
        raise ValueError(f"parados_na_distancia='{modo}' inválido; use um de: {', '.join(MODOS_PARADOS)}")

    sem_projecao = []
    if usar_plano_chao:
        escala = 1.0
        sem_projecao = [o for o in objetos if o.get("mx") is None or o.get("my") is None]
        objetos = [
            {**o, "x": o["mx"], "y": o["my"]}
            for o in objetos if o.get("mx") is not None and o.get("my") is not None
        ]

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

    papeis = [papeis_na_distancia(obj, historico, escala, modo) for obj in objetos]

    distancias = {}
    for i, obj_a in enumerate(objetos):
        e_alvo, _ = papeis[i]
        if not e_alvo:
            distancias[obj_a["track_id"]] = None
            continue
        menor, vizinho = None, None
        for j, obj_b in enumerate(objetos):
            _, pode_ser_vizinho = papeis[j]
            if i == j or not pode_ser_vizinho:
                continue
            d = calcular_distancia(obj_a, obj_b, escala)
            if menor is None or d < menor:
                menor, vizinho = d, obj_b["track_id"]
        distancias[obj_a["track_id"]] = menor
        if vizinhos is not None and obj_a["track_id"] is not None:
            vizinhos[obj_a["track_id"]] = vizinho

    for obj in sem_projecao:
        velocidades[obj["track_id"]] = None
        distancias[obj["track_id"]] = None

    return velocidades, distancias


def papeis_na_distancia(obj, historico, escala, modo=None):
    """
    Retorna (e_alvo, pode_ser_vizinho) para o cálculo de distância (ver
    atualizar_historico_e_calcular).

    Pedestres e bicicletas: nenhum dos dois papéis, em qualquer modo.
    Parado: modo "alvo_e_vizinho" -> nenhum; modo "so_alvo" -> não é alvo, mas
    pode ser vizinho de quem se move.
    """
    modo = PARADOS_NA_DISTANCIA if modo is None else modo
    if obj.get("vehicle_type") in CLASSES_IGNORADAS_DISTANCIA:
        return False, False
    tid = obj["track_id"]
    if tid is None:
        return True, True  # sem histórico não há como dizer que está parado
    parado = esta_parado(
        list(historico[tid]), escala, LIMIAR_PARADO_KMH, LIMIAR_PARADO_PX_S, MIN_PONTOS_PARADO
    )
    if not parado:
        return True, True
    return False, modo == "so_alvo"


def objeto_entra_na_distancia(obj, historico, escala):
    """True se o objeto participa do cálculo de distância nos DOIS papéis (modo
    "alvo_e_vizinho"). Mantida por compatibilidade; o cálculo usa papeis_na_distancia."""
    return papeis_na_distancia(obj, historico, escala, "alvo_e_vizinho") == (True, True)


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


def calcular_previsoes(objetos, historico, escala, ts, parados_na_distancia=None,
                       horizonte_s=None, limiar_m=None, somente_alvo=None):
    """
    Predição de curto prazo: para cada alvo (moto, ver RISCO_SOMENTE_ALVO), projeta
    a posição dele e dos vizinhos elegíveis (mesmos papéis do cálculo de distância)
    para os próximos `horizonte_s` segundos, com movimento uniforme, e procura a
    menor distância prevista.

    Retorna ({track_id: {...}}, {track_id: {"pos", "vel"}}):
      - previsões: só para quem tem aproximação PREVISTA, isto é, menor distância
        prevista < limiar e distância atual >= limiar (se já está abaixo, é
        proximidade_perigosa, não predição). Campos: distancia_prevista,
        tempo_ate_s, vizinho, distancia_atual.
      - cinematica: posição (m) e velocidade vetorial (m/s) de cada alvo com
        histórico suficiente (usada pelo AvaliadorPredicao).
    `escala` deve estar em metros (1.0 no plano do chão). Sem calibração: ({}, {}).
    """
    if escala is None:
        return {}, {}
    modo = PARADOS_NA_DISTANCIA if parados_na_distancia is None else parados_na_distancia
    horizonte_s = HORIZONTE_PREDICAO_S if horizonte_s is None else horizonte_s
    limiar_m = LIMIAR_DISTANCIA_MINIMA_M if limiar_m is None else limiar_m
    somente_alvo = RISCO_SOMENTE_ALVO if somente_alvo is None else somente_alvo

    cinematica = {}
    for obj in objetos:
        tid = obj["track_id"]
        if tid is None or tid not in historico:
            continue
        hist = historico[tid]
        if not hist or hist[-1]["timestamp"] != ts:
            continue  # sem posição neste quadro (ex.: sem projeção)
        vel = estimar_velocidade_vetorial(
            hist, escala, janela=PREDICAO_JANELA_PONTOS, min_pontos=PREDICAO_MIN_PONTOS
        )
        if vel is None:
            continue
        cinematica[tid] = {"pos": posicao_atual_m(hist, escala), "vel": vel}

    previsoes = {}
    for obj_a in objetos:
        ta = obj_a["track_id"]
        if ta not in cinematica or not _gera_risco(obj_a, somente_alvo):
            continue
        e_alvo, _ = papeis_na_distancia(obj_a, historico, escala, modo)
        if not e_alvo:
            continue
        a = cinematica[ta]
        melhor = None
        for obj_b in objetos:
            tb = obj_b["track_id"]
            if tb == ta or tb not in cinematica:
                continue
            _, pode_ser_vizinho = papeis_na_distancia(obj_b, historico, escala, modo)
            if not pode_ser_vizinho:
                continue
            b = cinematica[tb]
            d_atual = ((a["pos"][0] - b["pos"][0]) ** 2 + (a["pos"][1] - b["pos"][1]) ** 2) ** 0.5
            d_prev, t_prev = menor_distancia_prevista(a["pos"], a["vel"], b["pos"], b["vel"], horizonte_s)
            if d_atual >= limiar_m > d_prev and (melhor is None or d_prev < melhor["distancia_prevista"]):
                melhor = {"distancia_prevista": d_prev, "tempo_ate_s": t_prev,
                          "vizinho": tb, "distancia_atual": d_atual}
        if melhor is not None:
            previsoes[ta] = melhor
    return previsoes, cinematica


def avaliar_predicao(avaliador, cinematica, ts, tipos_por_id):
    """
    Alimenta o AvaliadorPredicao: confere previsões vencidas contra as posições
    de agora e registra as novas. `tipos_por_id`: {track_id: tipo} dos veículos
    a avaliar. A avaliação usa TODOS os veículos (não só motos): motos ficam pouco
    tempo no quadro e quase nunca duram o horizonte inteiro; o erro de previsão é
    uma propriedade do movimento e da calibração, e o resumo separa as motos.
    """
    avaliador.conferir(ts, {tid: c["pos"] for tid, c in cinematica.items()})
    for tid, tipo in tipos_por_id.items():
        c = cinematica.get(tid)
        if c is not None:
            avaliador.registrar(ts, tid, c["pos"], c["vel"], tipo)


def _segundos_entre(ts_a, ts_b):
    """Diferença ts_a - ts_b em segundos; aceita datetime ou número (segundos)."""
    delta = ts_a - ts_b
    return delta.total_seconds() if hasattr(delta, "total_seconds") else float(delta)


def _gera_risco(obj, somente_alvo):
    """Só motocicletas geram score/eventos quando somente_alvo=True (veja config.RISCO_SOMENTE_ALVO)."""
    # objeto sem tipo informado não é descartado (compatível com quem chama sem classe)
    return (not somente_alvo) or obj.get("vehicle_type", "motorcycle") == "motorcycle"


def atualizar_zonas(objetos, zonas, zona_por_track, ts=None, somente_alvo=None):
    """
    Calcula a zona atual de cada objeto e detecta TRANSIÇÕES de entrada
    (para não gerar um evento repetido a cada frame que o veículo passa
    dentro da mesma zona; reentradas após sair, sim, geram novo evento).

    zona_por_track: dict mutável {track_id: nome_da_zona_ou_None}, mantido
        entre chamadas (estado do vídeo inteiro).

    Retorna (zonas_atuais: {track_id: nome|None}, entradas: lista de dicts
        prontos para db.salvar_eventos, só para quem ACABOU de entrar em uma zona).
    """
    somente_alvo = RISCO_SOMENTE_ALVO if somente_alvo is None else somente_alvo
    zonas_atuais = {}
    entradas = []
    ts = ts if ts is not None else datetime.now()

    for obj in objetos:
        tid = obj["track_id"]
        if tid is None or not _gera_risco(obj, somente_alvo):
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
                    tendencias=None, ts=None, distancia_em_metros=True, somente_alvo=None,
                    cooldown_s=None, previsoes=None):
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
    previsoes: saída de calcular_previsoes (1º item); gera o evento "proximidade_prevista",
        que NÃO entra no score.
    cooldown_s: intervalo mínimo entre eventos do mesmo tipo e veículo (padrão: config.COOLDOWN_EVENTO_S).
    somente_alvo: True = só motocicletas geram análise/evento (padrão: config.RISCO_SOMENTE_ALVO).
    distancia_em_metros: False quando não há calibração (a distância está em
        pixels). Pixels não são comparáveis ao limiar em metros, então nesse caso
        a distância é ignorada para evento/score (proximidade_perigosa não é
        avaliada). Padrão True: quem já passa metros não precisa mudar nada.

    Retorna:
        analises: lista de dicts prontos para db.salvar_analises_risco
            (um por track_id rastreado neste frame).
        eventos_transicao: lista de dicts prontos para db.salvar_eventos
            (só para quem ACABOU de entrar em uma das condições de
            EVENTOS_TRANSICAO).
    """
    somente_alvo = RISCO_SOMENTE_ALVO if somente_alvo is None else somente_alvo
    cooldown_s = COOLDOWN_EVENTO_S if cooldown_s is None else cooldown_s
    # último instante em que cada (track, tipo) gerou evento; guardado no mesmo
    # dict de estado, sob uma chave que não colide com track_id
    previsoes = previsoes or {}
    ultimos = estado_condicoes.setdefault("__ultimo_evento__", {})
    analises = []
    eventos_transicao = []
    ts = ts if ts is not None else datetime.now()
    tendencias = tendencias or {}

    for obj in objetos:
        tid = obj["track_id"]
        if tid is None or not _gera_risco(obj, somente_alvo):
            continue

        velocidade = velocidades.get(tid)
        distancia = distancias.get(tid) if distancia_em_metros else None
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
        previsao = previsoes.get(tid)
        ativos_evento = list(eventos_ativos) + (["proximidade_prevista"] if previsao else [])
        for tipo_evento in EVENTOS_TRANSICAO:
            ativo_agora = tipo_evento in ativos_evento
            if ativo_agora and not estado_anterior.get(tipo_evento, False):
                ultimo = ultimos.get((tid, tipo_evento))
                if ultimo is not None and cooldown_s > 0 and _segundos_entre(ts, ultimo) < cooldown_s:
                    estado_anterior[tipo_evento] = ativo_agora
                    continue
                ultimos[(tid, tipo_evento)] = ts
                evento = {
                    "track_id": tid,
                    "event_type": tipo_evento,
                    "timestamp": ts,
                    "severity": nivel,
                    "speed_estimated": velocidade,
                    "distance": distancia,
                    "zona": zona,
                }
                if tipo_evento == "proximidade_prevista":
                    # distance = menor distância PREVISTA (m); o tempo até ela e o
                    # vizinho vão como campos extras (o banco só grava os conhecidos)
                    evento["distance"] = previsao["distancia_prevista"]
                    evento["tempo_ate_s"] = previsao["tempo_ate_s"]
                    evento["vizinho"] = previsao["vizinho"]
                eventos_transicao.append(evento)
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
