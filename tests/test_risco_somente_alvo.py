from datetime import datetime

from state import atualizar_zonas, calcular_riscos

ZONAS = [{"nome": "Z", "poligono": [(0, 0), (100, 0), (100, 100), (0, 100)]}]


def _obj(tid, tipo):
    return {"track_id": tid, "vehicle_type": tipo, "x": 50.0, "y": 50.0, "confidence": 0.9}


def _riscos(objetos, **kw):
    # velocidade bem acima do limiar para todos
    vel = {o["track_id"]: 200.0 for o in objetos}
    return calcular_riscos(objetos, vel, {}, {}, {}, ts=datetime(2026, 1, 1), **kw)


def test_so_moto_gera_analise_e_evento_por_padrao():
    analises, eventos = _riscos([_obj(1, "motorcycle"), _obj(2, "car"), _obj(3, "truck")], somente_alvo=True)
    assert {a["track_id"] for a in analises} == {1}
    assert {e["track_id"] for e in eventos} == {1}


def test_desligado_todos_geram():
    analises, eventos = _riscos([_obj(1, "motorcycle"), _obj(2, "car")], somente_alvo=False)
    assert {a["track_id"] for a in analises} == {1, 2}
    assert {e["track_id"] for e in eventos} == {1, 2}


def test_zona_so_para_moto():
    estado = {}
    atuais, entradas = atualizar_zonas([_obj(1, "motorcycle"), _obj(2, "car")], ZONAS, estado, somente_alvo=True)
    assert set(atuais) == {1} and {e["track_id"] for e in entradas} == {1}
    atuais, entradas = atualizar_zonas([_obj(1, "motorcycle"), _obj(2, "car")], ZONAS, {}, somente_alvo=False)
    assert set(atuais) == {1, 2}
