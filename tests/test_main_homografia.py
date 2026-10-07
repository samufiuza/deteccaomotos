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
    source, origem, no_display, batch, escala, zonas, calib_chao, parados = main_mod.parse_args()
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
    source, origem, no_display, batch, escala, zonas, calib_chao, parados = main_mod.parse_args()
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


# ---- --parados (modo dos objetos parados na distância) ----

def test_parse_args_parados_padrao_vem_da_config(main_mod, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "--source", "x.mp4"])
    resultado = main_mod.parse_args()
    assert resultado[7] == "alvo_e_vizinho"
    assert "alvo_e_vizinho" in capsys.readouterr().out


def test_parse_args_parados_so_alvo(main_mod, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--source", "x.mp4", "--parados", "so_alvo"])
    assert main_mod.parse_args()[7] == "so_alvo"


def test_parse_args_parados_invalido_encerra_com_erro(main_mod, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--source", "x.mp4", "--parados", "qualquer"])
    with pytest.raises(SystemExit):
        main_mod.parse_args()


def _rodar_cena_com_carro_parado(main_mod, monkeypatch, modo):
    """Carro parado + moto em movimento a ~1 m dele; devolve o nearest_distance da moto."""
    frame = np.zeros((720, 1280, 3), dtype="uint8")
    quadro = {"i": 0}

    def detector_falso(_frame, _model):
        i = quadro["i"]
        quadro["i"] += 1
        carro = {"track_id": 1, "vehicle_type": "car", "confidence": 0.9,
                 "x": 500.0, "y": 300.0, "bbox": (480, 280, 520, 320)}
        moto = {"track_id": 2, "vehicle_type": "motorcycle", "confidence": 0.9,
                "x": 400.0 + 5 * i, "y": 310.0, "bbox": (380 + 5 * i, 290, 420 + 5 * i, 330)}
        return [carro, moto], None

    monkeypatch.setattr(main_mod, "detectar_e_rastrear", detector_falso)
    estado = main_mod.novo_estado()
    registros = None
    for i in range(8):
        saida = main_mod.processar_frame(
            frame, None, T0 + timedelta(seconds=i * 0.1), estado, 0.1, [], parados_na_distancia=modo
        )
        registros = saida[1]
    return {r["track_id"]: r["nearest_distance"] for r in registros}


def test_processar_frame_modo_padrao_ignora_carro_parado(main_mod, monkeypatch):
    dist = _rodar_cena_com_carro_parado(main_mod, monkeypatch, "alvo_e_vizinho")
    assert dist[2] is None


def test_processar_frame_so_alvo_moto_enxerga_carro_parado(main_mod, monkeypatch):
    dist = _rodar_cena_com_carro_parado(main_mod, monkeypatch, "so_alvo")
    assert dist[2] is not None and dist[2] > 0
    assert dist[1] is None  # o carro parado continua sem evento para si


# ---- distância em pixels (sem calibração) não vira evento ----

def _cena_dois_veiculos_proximos(main_mod, monkeypatch, escala, H_chao=None, dx=15.0):
    """Dois carros com centros a `dx` px um do outro (padrão 15 px = 1,5 m se a escala for 0,1 m/px)."""
    frame = np.zeros((720, 1280, 3), dtype="uint8")

    def detector_falso(_frame, _model):
        a = {"track_id": 1, "vehicle_type": "car", "confidence": 0.9,
             "x": 500.0, "y": 300.0, "bbox": (480, 280, 520, 320)}
        b = {"track_id": 2, "vehicle_type": "car", "confidence": 0.9,
             "x": 500.0 + dx, "y": 300.0, "bbox": (480 + dx, 280, 520 + dx, 320)}
        return [a, b], None

    monkeypatch.setattr(main_mod, "detectar_e_rastrear", detector_falso)
    saida = main_mod.processar_frame(frame, None, T0, main_mod.novo_estado(), escala, [], H_chao=H_chao)
    return saida[4], saida[5]  # entradas (eventos), analises


def test_sem_calibracao_distancia_em_pixels_nao_gera_proximidade(main_mod, monkeypatch):
    # 1,5 PIXEL: abaixo do limiar de 2,0 se (erradamente) fosse lido como metros
    eventos, analises = _cena_dois_veiculos_proximos(main_mod, monkeypatch, escala=None, dx=1.5)
    assert "proximidade_perigosa" not in {e["event_type"] for e in eventos}
    assert all(a["risk_score"] == 0 for a in analises)


def test_com_escala_simples_a_proximidade_e_avaliada(main_mod, monkeypatch):
    eventos, _ = _cena_dois_veiculos_proximos(main_mod, monkeypatch, escala=0.1)  # 15 px = 1,5 m
    assert "proximidade_perigosa" in {e["event_type"] for e in eventos}


def test_com_homografia_a_proximidade_e_avaliada(main_mod, monkeypatch):
    # homografia trivial: 1 px = 0,1 m no chão (ponto de contato = base da caixa)
    H = np.diag([0.1, 0.1, 1.0])
    eventos, _ = _cena_dois_veiculos_proximos(main_mod, monkeypatch, escala=None, H_chao=H)
    assert "proximidade_perigosa" in {e["event_type"] for e in eventos}
