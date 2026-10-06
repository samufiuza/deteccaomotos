from collections import defaultdict, deque
from datetime import datetime, timedelta

from state import atualizar_historico_e_calcular

T0 = datetime(2026, 1, 1)
ESCALA = 0.1


def obj(tid, tipo, x, y=0):
    return {"track_id": tid, "vehicle_type": tipo, "x": x, "y": y}


def rodar(quadros, escala=ESCALA, dt=0.1):
    """quadros: lista de listas de objetos; retorna (distancias, vizinhos) do último quadro."""
    historico = defaultdict(deque)
    for i, objetos in enumerate(quadros):
        vizinhos = {}
        _, dist = atualizar_historico_e_calcular(objetos, historico, escala, T0 + timedelta(seconds=i * dt), vizinhos)
    return dist, vizinhos


def test_pedestre_nao_conta_como_vizinho():
    # manequim/pedestre colado na moto não gera proximidade
    dist, _ = rodar([[obj(1, "motorcycle", 0), obj(2, "pedestrian", 5)]])
    assert dist[1] is None
    assert dist[2] is None


def test_bicicleta_nao_conta_como_vizinho():
    dist, _ = rodar([[obj(1, "motorcycle", 0), obj(2, "bicycle", 5), obj(3, "car", 100)]])
    assert dist[1] == 100 * ESCALA  # vizinho válido é o carro, não a bicicleta
    assert dist[2] is None


def test_objeto_parado_e_ignorado_depois_de_historico_suficiente():
    # carro 2 parado em x=50; moto 1 andando 10 px/quadro (= 10 m/s)
    quadros = [[obj(1, "motorcycle", i * 10), obj(2, "car", 50)] for i in range(6)]
    dist, _ = rodar(quadros)
    assert dist[1] is None  # único vizinho está parado
    assert dist[2] is None  # o parado também não recebe distância


def test_objeto_recem_aparecido_ainda_conta():
    # com só 1 quadro não dá para afirmar que está parado
    dist, viz = rodar([[obj(1, "motorcycle", 0), obj(2, "car", 50)]])
    assert dist[1] == 50 * ESCALA
    assert viz[1] == 2


def test_dois_veiculos_em_movimento_contam():
    quadros = [[obj(1, "motorcycle", i * 10), obj(2, "car", 100 + i * 10)] for i in range(6)]
    dist, viz = rodar(quadros)
    assert dist[1] == 100 * ESCALA
    assert viz == {1: 2, 2: 1}


def test_parado_sem_calibracao_usa_pixels_por_segundo():
    quadros = [[obj(1, "motorcycle", i * 10), obj(2, "car", 300)] for i in range(6)]
    dist, _ = rodar(quadros, escala=None)
    assert dist[1] is None  # carro parado (0 px/s) ignorado mesmo sem calibração
