from collections import defaultdict, deque
from datetime import datetime, timedelta

import pytest

from risk import (
    detectar_mudanca_brusca,
    calcular_velocidade_aproximacao,
    detectar_eventos_ativos,
    calcular_score,
)
from state import calcular_tendencias, calcular_riscos
from config import PESOS_RISCO

T0 = datetime(2026, 1, 1, 12, 0, 0)
DT = 0.1  # 10 quadros por segundo
ESCALA = 0.1  # 0,1 m por pixel


def trajetoria(pontos_xy, dt=DT):
    return [{"x": x, "y": y, "timestamp": T0 + timedelta(seconds=i * dt)} for i, (x, y) in enumerate(pontos_xy)]


def brusca(hist, escala=ESCALA):
    return detectar_mudanca_brusca(hist, escala, limiar_angulo_graus=45,
                                   limiar_aceleracao_m_s2=6.0, min_deslocamento_m=0.5, janela=6)


# ---- detectar_mudanca_brusca ----

def test_reta_velocidade_constante_nao_e_brusca():
    hist = trajetoria([(i * 10, 0) for i in range(6)])  # 1 m/quadro = 10 m/s constante
    assert brusca(hist) is False


def test_curva_de_90_graus_e_brusca():
    hist = trajetoria([(0, 0), (10, 0), (20, 0), (30, 0), (30, 10), (30, 20)])
    assert brusca(hist) is True


def test_curva_suave_nao_e_brusca():
    # ~20 graus entre a 1ª e a 2ª metade
    hist = trajetoria([(0, 0), (10, 0), (20, 0), (30, 0), (39, 3), (48, 6)])
    assert brusca(hist) is False


def test_freada_brusca_e_detectada():
    # 1ª metade a 10 m/s, 2ª metade quase parado -> desaceleração ~ 30 m/s²
    hist = trajetoria([(0, 0), (10, 0), (20, 0), (30, 0), (31, 0), (32, 0)])
    assert brusca(hist) is True


def test_freada_suave_nao_e_brusca():
    # 10 m/s -> 9,5 m/s em ~0,3 s: ~1,7 m/s²
    hist = trajetoria([(0, 0), (10, 0), (20, 0), (30, 0), (39.5, 0), (49, 0)])
    assert brusca(hist) is False


def test_tremor_de_veiculo_parado_nao_e_curva():
    # bounding box "tremendo" 1-2 px (0,1-0,2 m) em várias direções
    hist = trajetoria([(100, 100), (101, 100), (100, 101), (101, 101), (100, 100), (101, 100)])
    assert brusca(hist) is False


def test_sem_calibracao_nao_avalia():
    hist = trajetoria([(0, 0), (10, 0), (20, 0), (30, 0), (30, 10), (30, 20)])
    assert brusca(hist, escala=None) is False


def test_historico_curto_nao_avalia():
    assert brusca(trajetoria([(0, 0), (10, 0)])) is False


def test_timestamps_repetidos_nao_quebram():
    hist = [{"x": i, "y": 0, "timestamp": T0} for i in range(6)]
    assert brusca(hist) is False


# ---- calcular_velocidade_aproximacao ----

def hist_dist(valores, vizinhos=None, dt=DT):
    vizinhos = vizinhos or [7] * len(valores)
    return [{"distancia": d, "vizinho": v, "timestamp": T0 + timedelta(seconds=i * dt)}
            for i, (d, v) in enumerate(zip(valores, vizinhos))]


def test_aproximacao_positiva_quando_distancia_cai():
    v = calcular_velocidade_aproximacao(hist_dist([10, 9.5, 9, 8.5, 8]))  # 2 m em 0,4 s
    assert v == pytest.approx(5.0)


def test_afastamento_da_valor_negativo():
    v = calcular_velocidade_aproximacao(hist_dist([8, 9, 10]))
    assert v < 0


def test_troca_de_vizinho_reinicia_a_sequencia():
    # a queda 10 -> 3 é troca de vizinho (7 -> 9), não aproximação
    v = calcular_velocidade_aproximacao(hist_dist([10, 10, 3, 3], vizinhos=[7, 7, 9, 9]))
    assert v == pytest.approx(0.0)


def test_aproximacao_sem_dados_suficientes():
    assert calcular_velocidade_aproximacao([]) is None
    assert calcular_velocidade_aproximacao(hist_dist([5])) is None


# ---- integração com eventos e score ----

def test_eventos_de_tendencia_ativos():
    eventos = detectar_eventos_ativos(30, 10, None, 60, 2.0,
                                      mudanca_brusca=True, velocidade_aproximacao=4.0,
                                      limiar_aproximacao=3.0)
    assert set(eventos) == {"mudanca_brusca", "aproximacao_rapida"}


def test_aproximacao_abaixo_do_limiar_nao_ativa():
    eventos = detectar_eventos_ativos(30, 10, None, 60, 2.0,
                                      velocidade_aproximacao=2.9, limiar_aproximacao=3.0)
    assert eventos == []


def test_todas_as_condicoes_somam_100():
    todos = ["velocidade_elevada", "proximidade_perigosa", "zona_risco", "mudanca_brusca", "aproximacao_rapida"]
    assert calcular_score(todos, PESOS_RISCO) == (100, "alto")


def test_calcular_tendencias_sem_calibracao():
    objetos = [{"track_id": 1, "x": 0, "y": 0}]
    historico = defaultdict(deque)
    tend = calcular_tendencias(objetos, historico, {1: 5}, {1: 2}, defaultdict(deque), None, T0)
    assert tend == {1: {"mudanca_brusca": False, "velocidade_aproximacao": None}}


def test_calcular_tendencias_detecta_aproximacao_ao_longo_dos_quadros():
    objetos = [{"track_id": 1, "x": 0, "y": 0}]
    historico = defaultdict(deque)
    hist_d = defaultdict(deque)
    tend = None
    for i, d in enumerate([10, 9.5, 9, 8.5]):
        ts = T0 + timedelta(seconds=i * DT)
        tend = calcular_tendencias(objetos, historico, {1: d}, {1: 2}, hist_d, ESCALA, ts)
    assert tend[1]["velocidade_aproximacao"] == pytest.approx(5.0)


def test_calcular_tendencias_distancia_none_interrompe_sequencia():
    objetos = [{"track_id": 1, "x": 0, "y": 0}]
    historico = defaultdict(deque)
    hist_d = defaultdict(deque)
    calcular_tendencias(objetos, historico, {1: 10}, {1: 2}, hist_d, ESCALA, T0)
    tend = calcular_tendencias(objetos, historico, {1: None}, {1: None}, hist_d,
                               ESCALA, T0 + timedelta(seconds=DT))
    assert tend[1]["velocidade_aproximacao"] is None
    assert len(hist_d[1]) == 0


def test_evento_mudanca_brusca_so_na_transicao():
    objetos = [{"track_id": 1}]
    estado = {}
    args = ({1: 30}, {1: 10}, {1: None}, estado)
    _, ev1 = calcular_riscos(objetos, *args, tendencias={1: {"mudanca_brusca": True}})
    _, ev2 = calcular_riscos(objetos, *args, tendencias={1: {"mudanca_brusca": True}})
    assert [e["event_type"] for e in ev1] == ["mudanca_brusca"]
    assert ev2 == []


def test_evento_aproximacao_rapida_entra_no_score():
    objetos = [{"track_id": 1}]
    analises, eventos = calcular_riscos(
        objetos, {1: 30}, {1: 10}, {1: None}, {},
        tendencias={1: {"velocidade_aproximacao": 5.0}},
    )
    assert analises[0]["risk_score"] == PESOS_RISCO["aproximacao_rapida"]
    assert [e["event_type"] for e in eventos] == ["aproximacao_rapida"]


def test_ts_informado_e_usado_nas_analises_e_eventos():
    analises, eventos = calcular_riscos([{"track_id": 1}], {1: 90}, {1: 10}, {1: None}, {}, ts=T0)
    assert analises[0]["timestamp"] == T0
    assert eventos[0]["timestamp"] == T0
