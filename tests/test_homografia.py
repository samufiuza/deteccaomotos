import json

import numpy as np
import pytest

from calibration import (
    calcular_homografia,
    aplicar_homografia,
    distancia_no_chao,
    reescalar_homografia,
    projetar_objetos,
    salvar_calibracao,
    carregar_calibracao,
)

# Retângulo do chão: 3,5 m de largura (X) por 20 m de comprimento (Y)
MUNDO = [(0, 0), (3.5, 0), (3.5, 20), (0, 20)]

# "Câmera" sintética: matriz que leva MUNDO -> IMAGEM com perspectiva forte
# (o fundo da rua converge, como numa câmera inclinada).
H_MUNDO_IMG = np.array([
    [100.0, 30.0, 300.0],
    [0.0, 20.0, 650.0],
    [0.0, 0.045, 1.0],
])


def _mundo_para_imagem(X, Y):
    v = H_MUNDO_IMG @ np.array([X, Y, 1.0])
    return float(v[0] / v[2]), float(v[1] / v[2])


@pytest.fixture
def imagem_pts():
    return [_mundo_para_imagem(X, Y) for X, Y in MUNDO]


def test_recupera_pontos_de_calibracao(imagem_pts):
    H = calcular_homografia(imagem_pts, MUNDO)
    for (x, y), (X, Y) in zip(imagem_pts, MUNDO):
        Xr, Yr = aplicar_homografia(H, x, y)
        assert Xr == pytest.approx(X, abs=1e-6)
        assert Yr == pytest.approx(Y, abs=1e-6)


def test_generaliza_para_pontos_dentro_do_retangulo(imagem_pts):
    H = calcular_homografia(imagem_pts, MUNDO)
    for X, Y in [(1.0, 5.0), (2.5, 12.0), (0.5, 18.0)]:
        x, y = _mundo_para_imagem(X, Y)
        Xr, Yr = aplicar_homografia(H, x, y)
        assert (Xr, Yr) == pytest.approx((X, Y), abs=1e-6)


def test_escala_varia_com_a_profundidade(imagem_pts):
    # o mesmo deslocamento em pixels vale MAIS metros no fundo da imagem do que
    # na frente — é isso que o fator único de escala não consegue representar
    H = calcular_homografia(imagem_pts, MUNDO)
    x_perto, y_perto = _mundo_para_imagem(1.75, 2.0)
    x_longe, y_longe = _mundo_para_imagem(1.75, 18.0)
    m_perto = distancia_no_chao(H, (x_perto, y_perto), (x_perto, y_perto - 10))
    m_longe = distancia_no_chao(H, (x_longe, y_longe), (x_longe, y_longe - 10))
    assert m_longe > 2 * m_perto


def test_distancia_no_chao_recupera_largura_real(imagem_pts):
    H = calcular_homografia(imagem_pts, MUNDO)
    # a largura da pista (3,5 m) a qualquer profundidade
    for Y in (3.0, 10.0, 17.0):
        a = _mundo_para_imagem(0.0, Y)
        b = _mundo_para_imagem(3.5, Y)
        assert distancia_no_chao(H, a, b) == pytest.approx(3.5, abs=1e-6)


def test_pontos_colineares_levantam_erro():
    img = [(0, 0), (10, 0), (20, 0), (30, 0)]
    with pytest.raises(ValueError):
        calcular_homografia(img, MUNDO)


def test_numero_errado_de_pontos_levanta_erro():
    with pytest.raises(ValueError):
        calcular_homografia([(0, 0), (1, 1), (2, 5)], MUNDO[:3])


def test_ponto_no_horizonte_retorna_none():
    H = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 0, 0.0]])  # denominador sempre 0
    assert aplicar_homografia(H, 10, 10) is None
    assert distancia_no_chao(H, (1, 1), (2, 2)) is None


def test_reescalar_mantem_a_mesma_posicao_no_mundo(imagem_pts):
    H = calcular_homografia(imagem_pts, MUNDO)
    x, y = _mundo_para_imagem(2.0, 7.0)
    H2 = reescalar_homografia(H, (1280, 720), (1920, 1080))  # 1,5x
    esperado = aplicar_homografia(H, x, y)
    obtido = aplicar_homografia(H2, x * 1.5, y * 1.5)
    assert obtido == pytest.approx(esperado, abs=1e-6)


def test_reescalar_com_proporcao_diferente_levanta_erro(imagem_pts):
    H = calcular_homografia(imagem_pts, MUNDO)
    with pytest.raises(ValueError):
        reescalar_homografia(H, (1280, 720), (1280, 960))  # 16:9 -> 4:3


def test_projetar_objetos_usa_a_base_da_caixa():
    H = np.diag([0.1, 0.1, 1.0])  # 1 px = 0,1 m, só para conferir o ponto usado
    objetos = [{"bbox": (100, 200, 140, 300)}]
    projetar_objetos(objetos, H)
    # base da caixa = (centro em x, y2) = (120, 300)  ->  (12,0 m ; 30,0 m)
    assert objetos[0]["mx"] == pytest.approx(12.0)
    assert objetos[0]["my"] == pytest.approx(30.0)


def test_projetar_objetos_falha_vira_none():
    H = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 0, 0.0]])
    objetos = [{"bbox": (0, 0, 10, 10)}]
    projetar_objetos(objetos, H)
    assert objetos[0]["mx"] is None and objetos[0]["my"] is None


def test_salvar_e_carregar_ida_e_volta(tmp_path, imagem_pts):
    H = calcular_homografia(imagem_pts, MUNDO)
    arq = tmp_path / "cal.json"
    salvar_calibracao(str(arq), H, imagem_pts, MUNDO, (1280, 720), descricao="teste")
    H2, res = carregar_calibracao(str(arq))
    assert res == (1280, 720)
    assert np.allclose(H, H2)


def test_salvar_preserva_zonas_existentes(tmp_path, imagem_pts):
    arq = tmp_path / "cal.json"
    arq.write_text(json.dumps({"zonas": [{"nome": "z", "poligono": [[0, 0], [1, 0], [1, 1]]}]}))
    H = calcular_homografia(imagem_pts, MUNDO)
    salvar_calibracao(str(arq), H, imagem_pts, MUNDO, (1280, 720))
    dados = json.loads(arq.read_text())
    assert "zonas" in dados and "homografia" in dados


def test_carregar_arquivo_sem_homografia_levanta_erro(tmp_path):
    arq = tmp_path / "so_zonas.json"
    arq.write_text(json.dumps({"zonas": []}))
    with pytest.raises(ValueError):
        carregar_calibracao(str(arq))
