"""
Lógica de estado do pipeline — histórico de posições e zonas de risco.

Fica separado de main.py de propósito: não depende de ultralytics nem de
psycopg2, então dá para testar (e importar) sem precisar instalar essas
dependências pesadas.
"""

from datetime import datetime

from risk import calcular_velocidade, calcular_distancia, checar_zona


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
