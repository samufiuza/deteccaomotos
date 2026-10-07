from datetime import datetime

from state import calcular_riscos

T = datetime(2026, 1, 1)


def _riscos(distancia, em_metros):
    objetos = [{"track_id": 1}]
    return calcular_riscos(objetos, {1: None}, {1: distancia}, {1: None}, {}, ts=T,
                           distancia_em_metros=em_metros)


def test_distancia_em_metros_abaixo_do_limiar_gera_proximidade():
    analises, eventos = _riscos(1.5, True)
    assert [e["event_type"] for e in eventos] == ["proximidade_perigosa"]
    assert analises[0]["risk_score"] == 25
    assert eventos[0]["distance"] == 1.5


def test_distancia_em_pixels_nao_gera_proximidade():
    # 1,5 "pixel" não é 1,5 metro: sem calibração a distância não vira evento
    analises, eventos = _riscos(1.5, False)
    assert eventos == []
    assert analises[0]["risk_score"] == 0


def test_padrao_continua_sendo_metros():
    # chamadas antigas (sem o parâmetro) mantêm o comportamento
    analises, eventos = calcular_riscos([{"track_id": 1}], {1: None}, {1: 1.5}, {1: None}, {}, ts=T)
    assert [e["event_type"] for e in eventos] == ["proximidade_perigosa"]
