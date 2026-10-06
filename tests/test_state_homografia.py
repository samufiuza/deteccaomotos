import math
from collections import defaultdict, deque
from datetime import datetime, timedelta

import numpy as np
import pytest

from calibration import calcular_homografia, calcular_escala, projetar_objetos
from risk import detectar_mudanca_brusca, esta_parado
from state import atualizar_historico_e_calcular

FPS = 30.0
VEL_MS = 10.0  # 10 m/s = 36 km/h
T0 = datetime(2026, 1, 1)


def _camera(h=8.0, theta_deg=35.0, f=1000.0, cx=640.0, cy=360.0):
    """Matriz mundo(X,Y,1) -> imagem de uma câmera pinhole a h metros de altura,
    inclinada theta graus para baixo, olhando ao longo do eixo Y."""
    t = math.radians(theta_deg)
    c, s = math.cos(t), math.sin(t)
    return np.array([
        [f, cx * c, cx * h * s],
        [0, cy * c - f * s, cy * h * s + f * h * c],
        [0, c, h * s],
    ])


H_MI = _camera()


def _mundo_para_imagem(X, Y):
    v = H_MI @ np.array([X, Y, 1.0])
    return float(v[0] / v[2]), float(v[1] / v[2])


MUNDO = [(-1.75, 8), (1.75, 8), (1.75, 28), (-1.75, 28)]
H_CALIB = calcular_homografia([_mundo_para_imagem(*p) for p in MUNDO], MUNDO)


def _obj(track_id, X, Y, tipo="car"):
    x, y = _mundo_para_imagem(X, Y)
    return {"track_id": track_id, "vehicle_type": tipo, "x": x, "y": y - 20,
            "bbox": (x - 20, y - 40, x + 20, y)}


def _novo_historico():
    return defaultdict(lambda: deque(maxlen=15))


def _simular_veiculo(Y0, usar_chao, escala=None):
    hist = _novo_historico()
    vel = None
    for i in range(10):
        Y = Y0 + VEL_MS * (i / FPS)
        objs = [_obj(1, 0.0, Y)]
        if usar_chao:
            projetar_objetos(objs, H_CALIB)
        v, _ = atualizar_historico_e_calcular(
            objs, hist, escala, T0 + timedelta(seconds=i / FPS), usar_plano_chao=usar_chao
        )
        vel = v[1]
    return vel


@pytest.mark.parametrize("Y0", [9.0, 17.0, 25.0])
def test_velocidade_correta_em_qualquer_profundidade(Y0):
    assert _simular_veiculo(Y0, usar_chao=True) == pytest.approx(36.0, abs=0.01)


def test_escala_unica_pela_largura_subestima_a_velocidade_ao_longo_da_via():
    # documenta POR QUE a homografia existe: uma escala única, calibrada pela
    # largura da pista, erra muito a velocidade longitudinal numa câmera inclinada
    a, b = _mundo_para_imagem(-1.75, 18), _mundo_para_imagem(1.75, 18)
    escala = calcular_escala(a, b, 3.5)
    longe = _simular_veiculo(25.0, usar_chao=False, escala=escala)
    assert longe < 0.5 * 36.0  # erra por mais de 50% ao fundo da cena
    assert _simular_veiculo(25.0, usar_chao=True) == pytest.approx(36.0, abs=0.01)


def test_distancia_lateral_em_metros_independe_da_profundidade():
    for Y in (10.0, 20.0, 27.0):
        objs = [_obj(1, -1.75, Y), _obj(2, 1.75, Y)]
        projetar_objetos(objs, H_CALIB)
        _, dist = atualizar_historico_e_calcular(objs, _novo_historico(), None, T0, usar_plano_chao=True)
        assert dist[1] == pytest.approx(3.5, abs=1e-6)
        assert dist[2] == pytest.approx(3.5, abs=1e-6)


def test_distancia_longitudinal_em_metros_e_vizinho_registrado():
    objs = [_obj(1, 0.0, 12.0), _obj(2, 0.0, 17.0)]
    projetar_objetos(objs, H_CALIB)
    vizinhos = {}
    _, dist = atualizar_historico_e_calcular(
        objs, _novo_historico(), None, T0, vizinhos, usar_plano_chao=True
    )
    assert dist[1] == pytest.approx(5.0, abs=1e-6)
    assert vizinhos == {1: 2, 2: 1}


def test_objeto_sem_projecao_e_ignorado():
    objs = [_obj(1, 0.0, 12.0), _obj(2, 0.0, 17.0)]
    projetar_objetos(objs, H_CALIB)
    objs[1]["mx"], objs[1]["my"] = None, None  # projeção falhou para o 2
    hist = _novo_historico()
    vel, dist = atualizar_historico_e_calcular(objs, hist, None, T0, usar_plano_chao=True)
    assert vel[2] is None
    assert dist[2] is None
    assert dist[1] is None  # sem outro objeto válido para medir distância
    assert len(hist[2]) == 0


def test_pedestre_continua_fora_da_distancia_no_plano_do_chao():
    # o filtro do Cowork (pedestre/bicicleta não contam) vale também em metros
    objs = [_obj(1, 0.0, 12.0, "motorcycle"), _obj(2, 1.0, 12.0, "pedestrian")]
    projetar_objetos(objs, H_CALIB)
    _, dist = atualizar_historico_e_calcular(objs, _novo_historico(), None, T0, usar_plano_chao=True)
    assert dist[1] is None and dist[2] is None


def test_objeto_parado_e_reconhecido_em_metros():
    # parado = abaixo de LIMIAR_PARADO_KMH; em metros, 0,01 m por quadro é ~1 km/h
    hist = _novo_historico()
    for i in range(6):
        objs = [_obj(1, 0.0, 12.0 + 0.01 * i)]
        projetar_objetos(objs, H_CALIB)
        atualizar_historico_e_calcular(objs, hist, None, T0 + timedelta(seconds=i / FPS), usar_plano_chao=True)
    assert esta_parado(list(hist[1]), 1.0, limiar_kmh=3.0, limiar_px_s=20.0, min_pontos=5) is True


def test_direcao_e_medida_no_plano_do_chao():
    # curva de 90° no chão (anda em X, depois em Y); o histórico guarda metros,
    # então a análise de tendência usa escala 1,0
    hist = _novo_historico()
    trajeto = [(-2.0, 12.0), (-1.0, 12.0), (0.0, 12.0), (1.0, 12.0), (1.0, 13.0), (1.0, 14.0)]
    for i, (X, Y) in enumerate(trajeto):
        objs = [_obj(1, X, Y)]
        projetar_objetos(objs, H_CALIB)
        atualizar_historico_e_calcular(objs, hist, None, T0 + timedelta(seconds=i / FPS), usar_plano_chao=True)
    assert detectar_mudanca_brusca(list(hist[1]), 1.0, 45, 6.0, 0.5, janela=6) is True


def test_reta_no_chao_nao_e_mudanca_brusca():
    hist = _novo_historico()
    for i in range(6):
        objs = [_obj(1, 0.0, 12.0 + i)]
        projetar_objetos(objs, H_CALIB)
        atualizar_historico_e_calcular(objs, hist, None, T0 + timedelta(seconds=i / FPS), usar_plano_chao=True)
    assert detectar_mudanca_brusca(list(hist[1]), 1.0, 45, 6.0, 0.5, janela=6) is False
