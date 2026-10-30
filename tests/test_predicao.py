import sys
import types
import importlib
from collections import deque
from datetime import datetime, timedelta

import numpy as np
import pytest

from predicao import (
    AvaliadorPredicao,
    estimar_velocidade_vetorial,
    menor_distancia_prevista,
    posicao_prevista,
)
from state import calcular_previsoes, calcular_riscos

T0 = datetime(2026, 1, 1)
FPS = 30.0


def _hist(posicoes_por_t, n=12):
    """posicoes_por_t: f(t) -> (x, y) em m. Devolve deque com n pontos a 30 fps, terminando em t=(n-1)/30."""
    h = deque(maxlen=15)
    for i in range(n):
        t = i / FPS
        x, y = posicoes_por_t(t)
        h.append({"x": x, "y": y, "timestamp": T0 + timedelta(seconds=t)})
    return h


# ---- velocidade vetorial e geometria ----

def test_velocidade_vetorial_movimento_uniforme():
    h = _hist(lambda t: (1.0 * t, 6.0 * t))
    vx, vy = estimar_velocidade_vetorial(h, 1.0)
    assert vx == pytest.approx(1.0, abs=1e-3) and vy == pytest.approx(6.0, abs=1e-3)


def test_velocidade_vetorial_aplica_escala():
    h = _hist(lambda t: (0.0, 60.0 * t))      # pixels
    _, vy = estimar_velocidade_vetorial(h, 0.1)
    assert vy == pytest.approx(6.0, abs=1e-3)


def test_velocidade_vetorial_sem_calibracao_ou_poucos_pontos():
    assert estimar_velocidade_vetorial(_hist(lambda t: (0, t)), None) is None
    assert estimar_velocidade_vetorial(_hist(lambda t: (0, t), n=3), 1.0) is None


def test_posicao_prevista():
    assert posicao_prevista((1.0, 2.0), (3.0, -1.0), 2.0) == (7.0, 0.0)


def test_menor_distancia_aproximacao_frontal():
    d, t = menor_distancia_prevista((0, 0), (5, 0), (10, 0), (0, 0), horizonte_s=3.0)
    assert d == pytest.approx(0.0, abs=1e-9) and t == pytest.approx(2.0)


def test_menor_distancia_limitada_ao_horizonte():
    d, t = menor_distancia_prevista((0, 0), (5, 0), (20, 0), (0, 0), horizonte_s=2.0)
    assert t == pytest.approx(2.0) and d == pytest.approx(10.0)


def test_menor_distancia_afastando_fica_no_instante_zero():
    d, t = menor_distancia_prevista((0, 0), (0, 0), (5, 0), (3, 0), horizonte_s=2.0)
    assert t == 0.0 and d == pytest.approx(5.0)


def test_menor_distancia_sem_movimento_relativo():
    d, t = menor_distancia_prevista((0, 0), (2, 0), (0, 3), (2, 0), horizonte_s=2.0)
    assert d == pytest.approx(3.0) and t == 0.0


# ---- previsões a partir do histórico ----

MOTO = {"track_id": 1, "vehicle_type": "motorcycle"}
CARRO = {"track_id": 2, "vehicle_type": "car"}


def _cena(y_carro0, v_carro=2.0, v_moto=6.0, x_carro=0.5):
    historico = {
        1: _hist(lambda t: (0.0, v_moto * t)),
        2: _hist(lambda t: (x_carro, y_carro0 + v_carro * t)),
    }
    ts = list(historico[1])[-1]["timestamp"]
    return historico, ts


def test_preve_aproximacao_antes_de_ficar_perto():
    historico, ts = _cena(y_carro0=8.0)           # folga ~8 m, fecha a 4 m/s -> encosta em ~2 s
    previsoes, cinematica = calcular_previsoes([MOTO, CARRO], historico, 1.0, ts)
    assert set(previsoes) == {1}
    p = previsoes[1]
    assert p["vizinho"] == 2 and p["distancia_atual"] >= 2.0
    assert p["distancia_prevista"] < 2.0 and 0.0 < p["tempo_ate_s"] <= 2.0
    assert set(cinematica) == {1, 2}


def test_nao_preve_quando_aproximacao_e_lenta_demais_para_o_horizonte():
    historico, ts = _cena(y_carro0=30.0)          # só chegaria depois dos 2 s
    previsoes, _ = calcular_previsoes([MOTO, CARRO], historico, 1.0, ts)
    assert previsoes == {}


def test_nao_preve_se_ja_esta_perto():
    historico, ts = _cena(y_carro0=0.3, v_carro=5.9)  # já a ~0,8 m: é proximidade_perigosa, não predição
    previsoes, _ = calcular_previsoes([MOTO, CARRO], historico, 1.0, ts)
    assert previsoes == {}


def test_carro_nao_e_alvo_quando_risco_so_para_motos():
    # o carro vem de trás, mais rápido que a moto: só a moto seria alvo, e ela se afasta
    historico = {1: _hist(lambda t: (0.0, 2.0 * t)), 2: _hist(lambda t: (0.5, -8.0 + 6.0 * t))}
    ts = list(historico[1])[-1]["timestamp"]
    previsoes, _ = calcular_previsoes([MOTO, CARRO], historico, 1.0, ts, somente_alvo=True)
    assert 2 not in previsoes
    previsoes_todos, _ = calcular_previsoes([MOTO, CARRO], historico, 1.0, ts, somente_alvo=False)
    assert 2 in previsoes_todos


def test_sem_calibracao_nao_preve():
    historico, ts = _cena(y_carro0=8.0)
    assert calcular_previsoes([MOTO, CARRO], historico, None, ts) == ({}, {})


# ---- evento e score ----

def test_evento_proximidade_prevista_nao_muda_o_score():
    historico, ts = _cena(y_carro0=8.0)
    previsoes, _ = calcular_previsoes([MOTO, CARRO], historico, 1.0, ts)
    vel = {1: 21.6, 2: 7.2}
    analises, eventos = calcular_riscos([MOTO, CARRO], vel, {1: 8.0, 2: None}, {}, {}, ts=ts, previsoes=previsoes)
    prev = [e for e in eventos if e["event_type"] == "proximidade_prevista"]
    assert len(prev) == 1 and prev[0]["track_id"] == 1
    assert prev[0]["distance"] == pytest.approx(previsoes[1]["distancia_prevista"])
    assert prev[0]["tempo_ate_s"] == pytest.approx(previsoes[1]["tempo_ate_s"])
    # score igual ao de quem não tem predição
    analises_sem, _ = calcular_riscos([MOTO, CARRO], vel, {1: 8.0, 2: None}, {}, {}, ts=ts)
    assert analises[0]["risk_score"] == analises_sem[0]["risk_score"]


def test_evento_prevista_so_na_transicao():
    historico, ts = _cena(y_carro0=8.0)
    previsoes, _ = calcular_previsoes([MOTO, CARRO], historico, 1.0, ts)
    estado = {}
    _, ev1 = calcular_riscos([MOTO], {1: 21.6}, {1: 8.0}, {}, estado, ts=ts, previsoes=previsoes)
    _, ev2 = calcular_riscos([MOTO], {1: 21.6}, {1: 8.0}, {}, estado, ts=ts + timedelta(seconds=0.03), previsoes=previsoes)
    assert sum(e["event_type"] == "proximidade_prevista" for e in ev1) == 1
    assert sum(e["event_type"] == "proximidade_prevista" for e in ev2) == 0


# ---- avaliador de erro ----

def _rodar_avaliador(f_real, vel_prevista, n_quadros=120, horizonte=2.0, perde_em=None):
    av = AvaliadorPredicao(horizonte)
    for i in range(n_quadros):
        t = i / FPS
        ts = T0 + timedelta(seconds=t)
        pos = f_real(t)
        pos_by = {} if (perde_em is not None and i >= perde_em) else {1: pos}
        av.conferir(ts, pos_by)
        if 1 in pos_by:
            av.registrar(ts, 1, pos, vel_prevista)
    return av


def test_avaliador_movimento_uniforme_erro_quase_zero():
    av = _rodar_avaliador(lambda t: (0.0, 6.0 * t), (0.0, 6.0))
    r = av.resumo()
    assert r["todos"]["n"] > 30
    assert r["todos"]["erro_medio_m"] < 0.01
    assert r["todos"]["erro_parado_medio_m"] > 10.0   # sem predição o erro seria ~12 m


def test_avaliador_aceleracao_gera_erro():
    # aceleração de 0,4 m/s²: a previsão (velocidade constante) fica atrás do real
    av = _rodar_avaliador(lambda t: (0.0, 6.0 * t + 0.2 * t * t), (0.0, 6.0))
    e = av.resumo()["todos"]["erro_medio_m"]
    assert 0.5 < e < 3.0


def test_avaliador_descarta_veiculo_perdido():
    av = _rodar_avaliador(lambda t: (0.0, 6.0 * t), (0.0, 6.0), n_quadros=120, perde_em=30)
    # quem foi registrado depois do quadro 30-60 não chega a ser conferido
    assert all(a["erro_prev"] < 0.01 for a in av.amostras)
    assert len(av.amostras) < 30


def test_avaliador_texto_sem_amostras():
    assert "nenhuma amostra" in AvaliadorPredicao(2.0).texto_resumo()


# ---- ponta a ponta no main (detector falso, homografia trivial 1 px = 0,1 m) ----

@pytest.fixture
def main_mod(monkeypatch):
    falso = types.ModuleType("ultralytics")
    falso.YOLO = lambda *a, **k: object()
    monkeypatch.setitem(sys.modules, "ultralytics", falso)
    for nome in ("main", "detector"):
        sys.modules.pop(nome, None)
    mod = importlib.import_module("main")
    yield mod
    for nome in ("main", "detector"):
        sys.modules.pop(nome, None)


def test_main_gera_evento_prevista_e_mede_erro(main_mod, monkeypatch):
    quadro = {"i": 0}

    def detector_falso(_f, _m):
        i = quadro["i"]
        moto_y = 2.0 * i               # 2 px/quadro = 6 m/s
        carro_y = 100.0 + 0.6667 * i   # ~2 m/s, 10 m à frente
        moto = {"track_id": 1, "vehicle_type": "motorcycle", "confidence": 0.9,
                "x": 50.0, "y": moto_y, "bbox": (30, moto_y - 40, 70, moto_y)}
        carro = {"track_id": 2, "vehicle_type": "car", "confidence": 0.9,
                 "x": 55.0, "y": carro_y, "bbox": (35, carro_y - 40, 75, carro_y)}
        return [moto, carro], None

    monkeypatch.setattr(main_mod, "detectar_e_rastrear", detector_falso)
    H = np.diag([0.1, 0.1, 1.0])
    estado = main_mod.novo_estado()
    frame = np.zeros((720, 1280, 3), dtype="uint8")
    tipos = []
    for i in range(100):
        quadro["i"] = i
        saida = main_mod.processar_frame(frame, None, T0 + timedelta(seconds=i / FPS), estado, None, [], H_chao=H)
        tipos += [(e["event_type"], e["track_id"]) for e in saida[4]]
    assert ("proximidade_prevista", 1) in tipos
    assert ("proximidade_prevista", 2) not in tipos       # risco só para a moto
    r = estado["avaliadores_predicao"][2.0].resumo()["todos"]
    assert r["n"] > 20 and r["erro_medio_m"] < 0.3
