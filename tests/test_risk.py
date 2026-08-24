from datetime import datetime, timedelta

import pytest

from risk import calcular_velocidade, calcular_distancia

ESCALA_TESTE = 0.1  # 1px = 0.1m, só para os testes


def _historico(deslocamentos_e_tempos, x0=0, y0=0, t0=None):
    """Helper: constrói um histórico [{x,y,timestamp}, ...] a partir de
    (dx, dy, dt_segundos) sucessivos."""
    t0 = t0 or datetime.now()
    pontos = [{"x": x0, "y": y0, "timestamp": t0}]
    x, y, t = x0, y0, t0
    for dx, dy, dt in deslocamentos_e_tempos:
        x, y = x + dx, y + dy
        t = t + timedelta(seconds=dt)
        pontos.append({"x": x, "y": y, "timestamp": t})
    return pontos


# ---- velocidade ----

def test_velocidade_sem_calibracao_retorna_none():
    hist = _historico([(100, 0, 1)])
    assert calcular_velocidade(hist, escala_px_para_metros=None) is None


def test_velocidade_historico_insuficiente_retorna_none():
    hist = [{"x": 0, "y": 0, "timestamp": datetime.now()}]  # só 1 ponto
    assert calcular_velocidade(hist, escala_px_para_metros=ESCALA_TESTE) is None


def test_velocidade_parada_e_zero():
    hist = _historico([(0, 0, 1), (0, 0, 1)])
    vel = calcular_velocidade(hist, ESCALA_TESTE)
    assert vel == pytest.approx(0.0)


def test_velocidade_caso_conhecido():
    # 100px em 1s, escala 0.1 m/px -> 10 m/s -> 36 km/h
    hist = _historico([(100, 0, 1)])
    vel = calcular_velocidade(hist, ESCALA_TESTE)
    assert vel == pytest.approx(36.0, rel=1e-3)


def test_velocidade_dt_zero_retorna_none():
    # dois pontos com o mesmo timestamp (bug comum: câmera travando/duplicando frame)
    t = datetime.now()
    hist = [
        {"x": 0, "y": 0, "timestamp": t},
        {"x": 50, "y": 0, "timestamp": t},
    ]
    assert calcular_velocidade(hist, ESCALA_TESTE) is None


def test_velocidade_nao_deve_ser_negativa_em_movimento_normal():
    hist = _historico([(50, 0, 1), (50, 0, 1)])
    vel = calcular_velocidade(hist, ESCALA_TESTE)
    assert vel >= 0


# ---- distância ----

def test_distancia_sem_calibracao_retorna_pixels():
    d = calcular_distancia({"x": 0, "y": 0}, {"x": 30, "y": 0}, escala_px_para_metros=None)
    assert d == pytest.approx(30.0)


def test_distancia_com_calibracao_retorna_metros():
    d = calcular_distancia({"x": 0, "y": 0}, {"x": 30, "y": 0}, ESCALA_TESTE)
    assert d == pytest.approx(3.0)


def test_distancia_mesmo_ponto_e_zero():
    d = calcular_distancia({"x": 10, "y": 10}, {"x": 10, "y": 10}, ESCALA_TESTE)
    assert d == pytest.approx(0.0)


def test_distancia_e_simetrica():
    a, b = {"x": 0, "y": 0}, {"x": 40, "y": 30}
    assert calcular_distancia(a, b, ESCALA_TESTE) == pytest.approx(
        calcular_distancia(b, a, ESCALA_TESTE)
    )
