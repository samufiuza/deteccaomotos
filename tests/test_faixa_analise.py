import importlib
import sys
import types
from datetime import datetime, timedelta

import numpy as np
import pytest

from state import filtrar_faixa_analise, parse_faixa_analise

T0 = datetime(2026, 1, 1)


def test_parse_ok_e_com_ponto_e_virgula():
    assert parse_faixa_analise("-3.8,3.8,-5,45") == (-3.8, 3.8, -5.0, 45.0)
    assert parse_faixa_analise("-3.8;3.8;-5;45") == (-3.8, 3.8, -5.0, 45.0)


@pytest.mark.parametrize("texto", ["1,2,3", "a,b,c,d", "5,1,0,10", "0,10,5,5"])
def test_parse_invalido(texto):
    with pytest.raises(ValueError):
        parse_faixa_analise(texto)


def test_filtra_so_o_que_esta_dentro():
    objs = [
        {"track_id": 1, "mx": 0.0, "my": 10.0},
        {"track_id": 2, "mx": 6.0, "my": 10.0},    # pista vizinha
        {"track_id": 3, "mx": 0.0, "my": 80.0},    # longe demais
        {"track_id": 4, "mx": None, "my": None},   # sem projeção
    ]
    assert [o["track_id"] for o in filtrar_faixa_analise(objs, (-3.8, 3.8, -5, 45))] == [1]
    assert filtrar_faixa_analise(objs, None) is objs


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


def test_main_ignora_veiculos_fora_da_faixa(main_mod, monkeypatch):
    def detector_falso(_f, _m):
        # H = 0,1 m/px: x=50px -> 5 m ; x=300px -> 30 m
        a = {"track_id": 1, "vehicle_type": "motorcycle", "confidence": 0.9, "x": 50.0, "y": 100.0,
             "bbox": (40, 60, 60, 100)}
        b = {"track_id": 2, "vehicle_type": "car", "confidence": 0.9, "x": 300.0, "y": 100.0,
             "bbox": (290, 60, 310, 100)}
        return [a, b], None

    monkeypatch.setattr(main_mod, "detectar_e_rastrear", detector_falso)
    monkeypatch.setattr(main_mod, "FAIXA_ANALISE", (0.0, 10.0, 0.0, 20.0))
    saida = main_mod.processar_frame(np.zeros((720, 1280, 3), "uint8"), None, T0, main_mod.novo_estado(),
                                     None, [], H_chao=np.diag([0.1, 0.1, 1.0]))
    assert [o["track_id"] for o in saida[0]] == [1]
    assert {r["track_id"] for r in saida[1]} == {1}
