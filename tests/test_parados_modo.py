import subprocess
import sys
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from state import atualizar_historico_e_calcular, papeis_na_distancia

T0 = datetime(2026, 1, 1)
ESCALA = 0.1  # 0,1 m por pixel
DT = 0.1      # 10 quadros por segundo


def obj(tid, tipo, x, y=0.0):
    return {"track_id": tid, "vehicle_type": tipo, "x": x, "y": y}


def rodar(posicoes_por_quadro, modo, n=8):
    """
    posicoes_por_quadro: função (i) -> lista de objetos do quadro i.
    Roda n quadros e devolve (distancias, vizinhos) do último.
    """
    historico = defaultdict(lambda: deque(maxlen=15))
    for i in range(n):
        vizinhos = {}
        _, dist = atualizar_historico_e_calcular(
            posicoes_por_quadro(i), historico, ESCALA, T0 + timedelta(seconds=i * DT),
            vizinhos, parados_na_distancia=modo,
        )
    return dist, vizinhos


def moto_entre_carros_parados(i):
    # carros 1 e 2 parados; moto 3 anda 5 px/quadro (0,5 m / 0,1 s = 5 m/s = 18 km/h)
    # e passa a ~1 m (10 px) do carro 1 em y
    return [
        obj(1, "car", 100.0, 0.0),
        obj(2, "car", 100.0, 40.0),
        obj(3, "motorcycle", 60.0 + 5 * i, 10.0),
    ]


# ---- modo padrão: comportamento atual do Cowork preservado ----

def test_alvo_e_vizinho_ignora_o_carro_parado_como_vizinho():
    dist, viz = rodar(moto_entre_carros_parados, "alvo_e_vizinho")
    assert dist[3] is None  # a moto não "enxerga" os carros parados
    assert dist[1] is None and dist[2] is None


def test_modo_padrao_da_config_e_alvo_e_vizinho():
    import config
    assert config.PARADOS_NA_DISTANCIA == "alvo_e_vizinho"
    assert config.MODOS_PARADOS == ("alvo_e_vizinho", "so_alvo")


def test_none_usa_o_padrao_da_config():
    historico = defaultdict(lambda: deque(maxlen=15))
    for i in range(8):
        _, dist = atualizar_historico_e_calcular(
            moto_entre_carros_parados(i), historico, ESCALA, T0 + timedelta(seconds=i * DT)
        )
    assert dist[3] is None  # igual a "alvo_e_vizinho"


# ---- modo so_alvo ----

def test_so_alvo_moto_em_movimento_enxerga_o_carro_parado():
    dist, viz = rodar(moto_entre_carros_parados, "so_alvo")
    # no último quadro a moto está em x=95: carro 1 em (100, 0) e moto em (95, 10)
    esperado = ((100 - 95) ** 2 + (0 - 10) ** 2) ** 0.5 * ESCALA
    assert dist[3] == pytest.approx(esperado)
    assert viz[3] == 1  # o vizinho mais próximo é o carro parado


def test_so_alvo_carros_parados_nao_geram_distancia_para_si():
    dist, viz = rodar(moto_entre_carros_parados, "so_alvo")
    assert dist[1] is None and dist[2] is None
    assert 1 not in viz and 2 not in viz


def test_so_alvo_dois_parados_colados_continuam_sem_evento():
    # fila parada: nada se move -> ninguém é alvo, mesmo com todos como possíveis vizinhos
    fila = lambda i: [obj(1, "car", 100.0), obj(2, "car", 110.0), obj(3, "car", 120.0)]
    dist, _ = rodar(fila, "so_alvo")
    assert dist == {1: None, 2: None, 3: None}


def test_so_alvo_dois_veiculos_em_movimento_continuam_contando():
    mov = lambda i: [obj(1, "car", 100.0 + 5 * i), obj(2, "motorcycle", 100.0 + 5 * i, 20.0)]
    dist, _ = rodar(mov, "so_alvo")
    assert dist[1] == pytest.approx(20 * ESCALA)
    assert dist[2] == pytest.approx(20 * ESCALA)


@pytest.mark.parametrize("modo", ["alvo_e_vizinho", "so_alvo"])
def test_pedestre_e_bicicleta_ficam_fora_nos_dois_modos(modo):
    cena = lambda i: [
        obj(1, "motorcycle", 60.0 + 5 * i, 0.0),
        obj(2, "pedestrian", 95.0, 5.0),   # em movimento ou não, não conta
        obj(3, "bicycle", 90.0, 5.0),
    ]
    dist, _ = rodar(cena, modo)
    assert dist[1] is None and dist[2] is None and dist[3] is None


def test_so_alvo_funciona_no_plano_do_chao():
    # posições já em metros (mx, my): carro parado a 1 m da moto que se move
    historico = defaultdict(lambda: deque(maxlen=15))
    for i in range(8):
        objs = [
            {"track_id": 1, "vehicle_type": "car", "x": 0, "y": 0, "mx": 10.0, "my": 0.0},
            {"track_id": 2, "vehicle_type": "motorcycle", "x": 0, "y": 0, "mx": 5.0 + 0.5 * i, "my": 1.0},
        ]
        _, dist = atualizar_historico_e_calcular(
            objs, historico, None, T0 + timedelta(seconds=i * DT),
            usar_plano_chao=True, parados_na_distancia="so_alvo",
        )
    esperado = ((10.0 - 8.5) ** 2 + 1.0) ** 0.5
    assert dist[2] == pytest.approx(esperado)
    assert dist[1] is None


# ---- papeis_na_distancia ----

def test_papeis_de_objeto_novo_sem_historico_suficiente():
    historico = defaultdict(lambda: deque(maxlen=15))
    # recém-aparecido: não dá para dizer que está parado -> alvo e vizinho
    assert papeis_na_distancia(obj(1, "car", 0), historico, ESCALA, "so_alvo") == (True, True)


# ---- validação ----

def test_modo_invalido_levanta_erro():
    with pytest.raises(ValueError):
        atualizar_historico_e_calcular([obj(1, "car", 0)], defaultdict(deque), ESCALA, T0,
                                       parados_na_distancia="qualquer_coisa")


def test_variavel_de_ambiente_invalida_falha_ao_importar_config():
    raiz = Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, "-c", "import config"], cwd=raiz, capture_output=True, text=True,
        env={"PARADOS_NA_DISTANCIA": "xyz", "PATH": ""},
    )
    assert r.returncode != 0
    assert "PARADOS_NA_DISTANCIA" in r.stderr


def test_variavel_de_ambiente_valida_e_aceita():
    raiz = Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, "-c", "import config; print(config.PARADOS_NA_DISTANCIA)"],
        cwd=raiz, capture_output=True, text=True,
        env={"PARADOS_NA_DISTANCIA": "so_alvo", "PATH": ""},
    )
    assert r.returncode == 0
    assert r.stdout.strip() == "so_alvo"
