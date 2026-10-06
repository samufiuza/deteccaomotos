"""
Testa a fiação do main.py com a calibração por homografia, SEM precisar do
YOLO real: o módulo `ultralytics` é substituído por um falso só durante estes
testes, e o detector é trocado por um gerador de objetos sintéticos.
"""
import importlib
import math
import sys
import types
from datetime import datetime, timedelta

import numpy as np
import pytest

from calibration import calcular_homografia, carregar_calibracao, salvar_calibracao

FPS = 30.0
T0 = datetime(2026, 1, 1)


def _camera(h=8.0, theta_deg=35.0, f=1000.0, cx=640.0, cy=360.0):
    t = math.radians(theta_deg)
    c, s = math.cos(t), math.sin(t)
    return np.array([
        [f, cx * c, cx * h * s],
        [0, cy * c - f * s, cy * h * s + f * h * c],
        [0, c, h * s],
    ])


H_MI = _camera()
MUNDO = [(-1.75, 8), (1.75, 8), (1.75, 28), (-1.75, 28)]


def _m2i(X, Y):
    v = H_MI @ np.array([X, Y, 1.0])
    return float(v[0] / v[2]), float(v[1] / v[2])


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


@pytest.fixture
def arquivo_calibracao(tmp_path):
    img = [_m2i(*p) for p in MUNDO]
    H = calcular_homografia(img, MUNDO)
    caminho = tmp_path / "cal.json"
    salvar_calibracao(str(caminho), H, img, MUNDO, (1280, 720))
    return str(caminho)


def _objeto_sintetico(Y, X=0.0, fator_resolucao=1.0, tipo="motorcycle", track_id=1):
    x, y = _m2i(X, Y)
    x, y = x * fator_resolucao, y * fator_resolucao
    larg, alt = 40 * fator_resolucao, 40 * fator_resolucao
    return {
        "track_id": track_id, "vehicle_type": tipo, "confidence": 0.9,
        "x": x, "y": y - alt / 2, "bbox": (x - larg / 2, y - alt, x + larg / 2, y),
    }


def _rodar(main_mod, monkeypatch, H_chao, escala, frame, gerar_objeto, n=10):
    """Roda n quadros (tempo do vídeo: 1/FPS por quadro). Devolve (velocidades do
    último quadro, lista com todos os eventos gerados)."""
    quadro = {"i": 0}

    def detector_falso(_frame, _model):
        obj = gerar_objeto(quadro["i"])
        quadro["i"] += 1
        return [obj], None

    monkeypatch.setattr(main_mod, "detectar_e_rastrear", detector_falso)
    estado = main_mod.novo_estado()
    velocidades, eventos = None, []
    for i in range(n):
        saida = main_mod.processar_frame(
            frame, None, T0 + timedelta(seconds=i / FPS), estado, escala, [], H_chao=H_chao
        )
        velocidades = saida[2]
        eventos.extend(saida[4])
    return velocidades, eventos


# ---- argumentos ----

def test_parse_args_carrega_a_homografia(main_mod, arquivo_calibracao, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "--source", "x.mp4", "--calib-arquivo", arquivo_calibracao])
    source, origem, no_display, batch, escala, zonas, calib_chao = main_mod.parse_args()
    assert calib_chao is not None
    H, resolucao = calib_chao
    assert H.shape == (3, 3) and resolucao == (1280, 720)
    assert "homografia carregada" in capsys.readouterr().out


def test_parse_args_arquivo_inexistente_encerra_com_erro(main_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--source", "x.mp4", "--calib-arquivo", str(tmp_path / "nao_existe.json")])
    with pytest.raises(SystemExit):
        main_mod.parse_args()


def test_parse_args_sem_homografia_mantem_comportamento_antigo(main_mod, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--source", "x.mp4", "--calib-p1", "0,0", "--calib-p2", "10,0", "--calib-dist", "1"])
    source, origem, no_display, batch, escala, zonas, calib_chao = main_mod.parse_args()
    assert escala == pytest.approx(0.1)  # escala simples
    assert calib_chao is None
    assert origem == "x.mp4"  # --origem do Cowork continua funcionando


# ---- ajuste à resolução ----

def test_preparar_homografia_sem_calibracao_retorna_none(main_mod):
    assert main_mod.preparar_homografia(None, np.zeros((10, 10, 3), dtype="uint8")) is None


def test_preparar_homografia_proporcao_diferente_levanta_erro(main_mod, arquivo_calibracao):
    calib = carregar_calibracao(arquivo_calibracao)
    with pytest.raises(ValueError):
        main_mod.preparar_homografia(calib, np.zeros((960, 1280, 3), dtype="uint8"))  # 4:3


# ---- pipeline ----

def test_pipeline_com_homografia_mesma_resolucao(main_mod, arquivo_calibracao, monkeypatch):
    calib = carregar_calibracao(arquivo_calibracao)
    frame = np.zeros((720, 1280, 3), dtype="uint8")
    H = main_mod.preparar_homografia(calib, frame)
    vel, _ = _rodar(main_mod, monkeypatch, H, None, frame, lambda i: _objeto_sintetico(17.0 + 10.0 * i / FPS))
    assert vel[1] == pytest.approx(36.0, abs=0.05)


def test_pipeline_com_homografia_video_em_outra_resolucao(main_mod, arquivo_calibracao, monkeypatch, capsys):
    calib = carregar_calibracao(arquivo_calibracao)
    frame = np.zeros((1080, 1920, 3), dtype="uint8")  # 1,5x a resolução da calibração
    H = main_mod.preparar_homografia(calib, frame)
    assert "ajustando a homografia" in capsys.readouterr().out
    vel, _ = _rodar(
        main_mod, monkeypatch, H, None, frame,
        lambda i: _objeto_sintetico(17.0 + 10.0 * i / FPS, fator_resolucao=1.5),
    )
    assert vel[1] == pytest.approx(36.0, abs=0.05)


def test_tendencia_usa_metros_com_homografia(main_mod, arquivo_calibracao, monkeypatch):
    # Regressão da fusão: com homografia o histórico guarda METROS, então a análise
    # de tendência precisa receber escala 1,0. Se recebesse escala None, mudança
    # brusca nunca seria avaliada (sem calibração ela devolve False).
    calib = carregar_calibracao(arquivo_calibracao)
    frame = np.zeros((720, 1280, 3), dtype="uint8")
    H = main_mod.preparar_homografia(calib, frame)
    trajeto = [(-2.0, 12.0), (-1.0, 12.0), (0.0, 12.0), (1.0, 12.0), (1.0, 13.0), (1.0, 14.0)]
    _, eventos = _rodar(
        main_mod, monkeypatch, H, None, frame,
        lambda i: _objeto_sintetico(trajeto[i][1], X=trajeto[i][0]), n=len(trajeto),
    )
    assert "mudanca_brusca" in {e["event_type"] for e in eventos}


def test_sem_calibracao_tendencia_nao_e_avaliada(main_mod, monkeypatch):
    frame = np.zeros((720, 1280, 3), dtype="uint8")
    trajeto = [(-2.0, 12.0), (-1.0, 12.0), (0.0, 12.0), (1.0, 12.0), (1.0, 13.0), (1.0, 14.0)]
    _, eventos = _rodar(
        main_mod, monkeypatch, None, None, frame,
        lambda i: _objeto_sintetico(trajeto[i][1], X=trajeto[i][0]), n=len(trajeto),
    )
    assert "mudanca_brusca" not in {e["event_type"] for e in eventos}


def test_pipeline_sem_homografia_continua_usando_pixels_e_escala(main_mod, monkeypatch):
    frame = np.zeros((720, 1280, 3), dtype="uint8")

    def gerar(i):
        return {"track_id": 1, "vehicle_type": "car", "confidence": 0.9,
                "x": 100.0 + 10.0 * i, "y": 300.0, "bbox": (90 + 10.0 * i, 280, 110 + 10.0 * i, 320)}

    vel, _ = _rodar(main_mod, monkeypatch, None, 0.1, frame, gerar)
    # 10 px/quadro * 0,1 m/px * 30 quadros/s = 30 m/s = 108 km/h
    assert vel[1] == pytest.approx(108.0, abs=0.1)
