import pytest
from calibration import calcular_escala, parse_calibracao


def test_calcular_escala_caso_simples():
    # 50 pixels representam 5 metros reais -> 0.1 m/px
    escala = calcular_escala((0, 0), (50, 0), 5)
    assert escala == pytest.approx(0.1)


def test_calcular_escala_pontos_na_diagonal():
    # distância euclidiana: (0,0) -> (3,4) = 5px, representando 10m reais
    escala = calcular_escala((0, 0), (3, 4), 10)
    assert escala == pytest.approx(2.0)


def test_calcular_escala_pontos_iguais_deve_falhar():
    with pytest.raises(ValueError):
        calcular_escala((10, 10), (10, 10), 5)


def test_parse_calibracao_completa():
    escala = parse_calibracao("0,0", "50,0", "5")
    assert escala == pytest.approx(0.1)


def test_parse_calibracao_incompleta_retorna_none():
    assert parse_calibracao(None, "50,0", "5") is None
    assert parse_calibracao("0,0", None, "5") is None
    assert parse_calibracao("0,0", "50,0", None) is None
    assert parse_calibracao("", "", "") is None
