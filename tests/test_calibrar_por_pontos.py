import math

import numpy as np
import pytest

from calibration import aplicar_homografia, calcular_homografia, carregar_calibracao
from calibrar_por_pontos import (
    carregar_pontos,
    cobertura_da_imagem,
    erros_leave_one_out,
    erros_reprojecao,
    escrever_modelo_csv,
    homografia_minimos_quadrados,
    latlon_para_metros,
    main,
    ponto_suspeito,
    validar_distancia,
)

# Homografia "verdadeira" (pixel -> metro) usada para gerar dados sintéticos.
H_VERDADEIRA = np.array([[0.05, 0.01, -20.0],
                         [0.002, 0.12, -40.0],
                         [0.0001, 0.004, 1.0]])

PIXELS = [(100, 400), (600, 380), (1100, 420), (300, 650), (900, 700), (640, 520), (200, 520)]


def _mundo(H, pixels):
    return [aplicar_homografia(H, x, y) for x, y in pixels]


# ---- conversão lat/lon -> metros ----

def test_latlon_um_milesimo_de_grau_de_latitude_vale_cerca_de_111_m():
    pts = latlon_para_metros([(-26.990, -48.630), (-26.989, -48.630)])
    assert math.dist(pts[0], pts[1]) == pytest.approx(111.19, abs=0.1)


def test_latlon_longitude_encolhe_com_o_cosseno_da_latitude():
    pts = latlon_para_metros([(-27.0, -48.630), (-27.0, -48.629)])
    esperado = 111.195 * math.cos(math.radians(27.0))
    assert math.dist(pts[0], pts[1]) == pytest.approx(esperado, abs=0.1)


def test_latlon_norte_e_positivo_leste_e_positivo():
    (x0, y0), (x1, y1) = latlon_para_metros([(-27.0, -48.0), (-26.999, -47.999)])
    assert y1 > y0 and x1 > x0


# ---- homografia por mínimos quadrados ----

def test_recupera_a_homografia_verdadeira_sem_ruido():
    mundo = _mundo(H_VERDADEIRA, PIXELS)
    H = homografia_minimos_quadrados(PIXELS, mundo)
    for x, y in [(50, 450), (700, 600), (1200, 400)]:
        esperado = aplicar_homografia(H_VERDADEIRA, x, y)
        obtido = aplicar_homografia(H, x, y)
        assert obtido == pytest.approx(esperado, abs=1e-6)


def test_com_quatro_pontos_coincide_com_a_solucao_exata():
    pix = PIXELS[:4]
    mundo = _mundo(H_VERDADEIRA, pix)
    H_ls = homografia_minimos_quadrados(pix, mundo)
    H_exata = calcular_homografia(pix, mundo)
    for x, y in [(300, 500), (800, 650)]:
        assert aplicar_homografia(H_ls, x, y) == pytest.approx(aplicar_homografia(H_exata, x, y), abs=1e-6)


def test_menos_de_quatro_pontos_levanta_erro():
    with pytest.raises(ValueError):
        homografia_minimos_quadrados(PIXELS[:3], _mundo(H_VERDADEIRA, PIXELS[:3]))


def test_numero_de_pontos_diferente_levanta_erro():
    with pytest.raises(ValueError):
        homografia_minimos_quadrados(PIXELS[:5], _mundo(H_VERDADEIRA, PIXELS[:4]))


def test_pontos_colineares_levantam_erro():
    pix = [(100, 100), (200, 200), (300, 300), (400, 400), (500, 500)]
    mundo = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)]
    with pytest.raises(ValueError):
        homografia_minimos_quadrados(pix, mundo)


def test_ruido_pequeno_no_pixel_mantem_distancias_proximas():
    rng = np.random.default_rng(42)
    pix_ruido = [(x + rng.normal(0, 0.5), y + rng.normal(0, 0.5)) for x, y in PIXELS]
    H = homografia_minimos_quadrados(pix_ruido, _mundo(H_VERDADEIRA, PIXELS))
    a, b = (200, 520), (900, 700)
    real = math.dist(aplicar_homografia(H_VERDADEIRA, *a), aplicar_homografia(H_VERDADEIRA, *b))
    previsto = math.dist(aplicar_homografia(H, *a), aplicar_homografia(H, *b))
    assert previsto == pytest.approx(real, rel=0.05)


# ---- erros e leave-one-out ----

def test_erro_de_reprojecao_e_zero_em_dados_exatos():
    mundo = _mundo(H_VERDADEIRA, PIXELS)
    H = homografia_minimos_quadrados(PIXELS, mundo)
    assert max(erros_reprojecao(H, PIXELS, mundo)) < 1e-6


def test_leave_one_out_exige_cinco_pontos():
    assert erros_leave_one_out(PIXELS[:4], _mundo(H_VERDADEIRA, PIXELS[:4])) is None


def test_leave_one_out_em_dados_exatos_e_quase_zero():
    erros = erros_leave_one_out(PIXELS, _mundo(H_VERDADEIRA, PIXELS))
    assert max(erros) < 1e-4


def test_ponto_com_medida_errada_aparece_no_leave_one_out():
    mundo = _mundo(H_VERDADEIRA, PIXELS)
    mundo[3] = (mundo[3][0] + 5.0, mundo[3][1])  # erro de 5 m num ponto
    loo = erros_leave_one_out(PIXELS, mundo)
    assert loo[3] == pytest.approx(5.0, abs=1e-3)  # sem o ponto ruim, o erro dele é a própria falha


def test_ponto_suspeito_identifica_o_ponto_com_medida_errada():
    mundo = _mundo(H_VERDADEIRA, PIXELS)
    mundo[3] = (mundo[3][0] + 5.0, mundo[3][1])
    indice, rms_com, rms_sem = ponto_suspeito(PIXELS, mundo)
    assert indice == 3
    assert rms_sem < 0.1 * rms_com


def test_ponto_suspeito_none_em_dados_limpos_ou_poucos_pontos():
    assert ponto_suspeito(PIXELS, _mundo(H_VERDADEIRA, PIXELS)) is None
    assert ponto_suspeito(PIXELS[:5], _mundo(H_VERDADEIRA, PIXELS[:5])) is None


# ---- validação de distância ----

def test_validar_distancia_mede_e_calcula_erro_percentual():
    mundo = _mundo(H_VERDADEIRA, PIXELS)
    H = homografia_minimos_quadrados(PIXELS, mundo)
    a, b = (200, 520), (900, 700)
    real = math.dist(aplicar_homografia(H_VERDADEIRA, *a), aplicar_homografia(H_VERDADEIRA, *b))
    medida, erro = validar_distancia(H, a, b, real)
    assert medida == pytest.approx(real, rel=1e-6)
    assert erro == pytest.approx(0.0, abs=1e-4)
    _, erro_sup = validar_distancia(H, a, b, real / 2)  # real menor que o previsto
    assert erro_sup == pytest.approx(100.0, abs=0.01)


def test_validar_distancia_real_invalida_retorna_none():
    H = homografia_minimos_quadrados(PIXELS, _mundo(H_VERDADEIRA, PIXELS))
    assert validar_distancia(H, (0, 0), (10, 10), 0) == (None, None)


# ---- cobertura ----

def test_cobertura_pontos_concentrados_e_pequena():
    pts = [(100, 100), (110, 100), (110, 110), (100, 110)]
    assert cobertura_da_imagem(pts, (1280, 720)) < 0.01


def test_cobertura_pontos_nos_cantos_e_total():
    pts = [(0, 0), (1280, 0), (1280, 720), (0, 720), (640, 360)]
    assert cobertura_da_imagem(pts, (1280, 720)) == pytest.approx(1.0)


def test_cobertura_colinear_e_zero():
    assert cobertura_da_imagem([(0, 0), (10, 10), (20, 20)], (1280, 720)) == 0.0


# ---- CSV ----

def test_csv_ponto_e_virgula_com_decimal_em_virgula(tmp_path):
    arq = tmp_path / "p.csv"
    arq.write_text(
        "nome;px;py;lat;lon\n"
        "A;482;423;-26,99010;-48,63000\n"
        "B;590;482;-26,99012;-48,63002\n"
        "C;745;570;-26,99015;-48,63004\n"
        "D;213;333;-26,99000;-48,62990\n",
        encoding="utf-8",
    )
    dados = carregar_pontos(str(arq))
    assert dados["nomes"] == ["A", "B", "C", "D"]
    assert dados["fonte"] == "latlon"
    assert dados["pontos_imagem"][0] == (482.0, 423.0)
    assert len(dados["pontos_mundo_m"]) == 4


def test_csv_em_metros_com_virgula_como_separador(tmp_path):
    arq = tmp_path / "p.csv"
    arq.write_text("nome,px,py,x_m,y_m\nA,1,2,0.5,1.5\nB,3,4,2.0,3.0\n", encoding="utf-8")
    dados = carregar_pontos(str(arq))
    assert dados["fonte"] == "metros"
    assert dados["pontos_mundo_m"] == [(0.5, 1.5), (2.0, 3.0)]


def test_csv_com_coordenada_em_branco_pede_preenchimento(tmp_path):
    arq = tmp_path / "p.csv"
    escrever_modelo_csv([(10, 20), (30, 40)], str(arq))
    with pytest.raises(ValueError, match="P1"):
        carregar_pontos(str(arq))


def test_csv_sem_colunas_de_coordenada_levanta_erro(tmp_path):
    arq = tmp_path / "p.csv"
    arq.write_text("nome;px;py\nA;1;2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        carregar_pontos(str(arq))


def test_modelo_csv_tem_pixels_e_lat_lon_vazios(tmp_path):
    arq = tmp_path / "m.csv"
    escrever_modelo_csv([(482, 423), (590, 482)], str(arq))
    linhas = arq.read_text(encoding="utf-8").splitlines()
    assert linhas[0] == "nome;px;py;lat;lon"
    assert linhas[1] == "P1;482;423;;"


# ---- programa principal (ponta a ponta) ----

def _csv_metros(tmp_path, pixels, mundo):
    arq = tmp_path / "p.csv"
    linhas = ["nome;px;py;x_m;y_m"]
    for i, ((px, py), (X, Y)) in enumerate(zip(pixels, mundo), start=1):
        linhas.append(f"P{i};{px};{py};{X:.6f};{Y:.6f}")
    arq.write_text("\n".join(linhas), encoding="utf-8")
    return str(arq)


def test_main_calibra_salva_json_e_valida(tmp_path, capsys):
    mundo = _mundo(H_VERDADEIRA, PIXELS)
    csv_path = _csv_metros(tmp_path, PIXELS, mundo)
    saida = str(tmp_path / "calib.json")
    a, b = (200, 520), (900, 700)
    real = math.dist(aplicar_homografia(H_VERDADEIRA, *a), aplicar_homografia(H_VERDADEIRA, *b))
    codigo = main([
        "--pontos", csv_path, "--resolucao", "1280x720", "--saida", saida,
        "--validacao", f"{a[0]},{a[1]},{b[0]},{b[1]},{real:.6f}",
    ])
    texto = capsys.readouterr().out
    assert codigo == 0
    assert "BOA" in texto
    assert "erro +0.0%" in texto or "erro -0.0%" in texto
    H, resolucao = carregar_calibracao(saida)
    assert resolucao == (1280, 720)
    assert aplicar_homografia(H, 640, 520) == pytest.approx(aplicar_homografia(H_VERDADEIRA, 640, 520), abs=1e-4)


def test_main_avisa_quando_o_erro_e_alto(tmp_path, capsys):
    mundo = _mundo(H_VERDADEIRA, PIXELS)
    mundo[2] = (mundo[2][0] + 30.0, mundo[2][1] - 20.0)
    csv_path = _csv_metros(tmp_path, PIXELS, mundo)
    codigo = main(["--pontos", csv_path, "--resolucao", "1280x720", "--saida", str(tmp_path / "c.json")])
    texto = capsys.readouterr().out
    assert codigo == 0
    assert "RUIM" in texto
    assert "ATENÇÃO" in texto
    assert "Ponto suspeito: P3" in texto


def test_main_com_quatro_pontos_avisa_que_nao_ha_como_estimar_erro(tmp_path, capsys):
    mundo = _mundo(H_VERDADEIRA, PIXELS[:4])
    csv_path = _csv_metros(tmp_path, PIXELS[:4], mundo)
    main(["--pontos", csv_path, "--resolucao", "1280x720", "--saida", str(tmp_path / "c.json")])
    assert "exatamente 4 pontos" in capsys.readouterr().out


def test_main_csv_incompleto_retorna_erro_sem_salvar(tmp_path, capsys):
    arq = tmp_path / "p.csv"
    escrever_modelo_csv([(1, 2), (3, 4), (5, 6), (7, 8)], str(arq))
    saida = tmp_path / "c.json"
    codigo = main(["--pontos", str(arq), "--resolucao", "1280x720", "--saida", str(saida)])
    assert codigo == 1
    assert not saida.exists()
    assert "ERRO" in capsys.readouterr().out


def test_main_sem_imagem_nem_resolucao_retorna_erro(tmp_path):
    arq = tmp_path / "p.csv"
    arq.write_text("nome;px;py;x_m;y_m\nA;1;2;0;0\n", encoding="utf-8")
    assert main(["--pontos", str(arq)]) == 2


# ---- restrições parciais (pistas de rodovia: linhas de borda com X conhecido) ----

from calibrar_por_pontos import ajustar_homografia, completar_mundo, pontos_transversais_horizontais  # noqa: E402

# Homografia mundo (X lateral, Y ao longo da via, metros) -> pixel de uma câmera olhando a via.
H_MUNDO_PARA_PIXEL = np.array([[1800.0, 288.0, 8640.0], [0.0, 100.0, 30000.0], [0.0, 1.0, 30.0]])
H_PIXEL_PARA_MUNDO = np.linalg.inv(H_MUNDO_PARA_PIXEL)


def _pixel(X, Y):
    v = H_MUNDO_PARA_PIXEL @ np.array([X, Y, 1.0])
    return (float(v[0] / v[2]), float(v[1] / v[2]))


def _cena_rodovia():
    """Pontas de traço no eixo (X, Y conhecidos) + pontos em linhas de borda (só X conhecido)."""
    img, mundo = [], []
    for Y in (0.0, 4.0, 16.0, 20.0, 32.0, 36.0):          # traços de 4 m a cada 16 m
        img.append(_pixel(0.0, Y))
        mundo.append((0.0, Y))
    for Y in (8.0, 24.0, 40.0):                            # linha de borda esquerda
        img.append(_pixel(-3.6, Y))
        mundo.append((-3.6, None))
    for Y in (10.0, 26.0, 42.0):                           # linha de borda direita
        img.append(_pixel(3.6, Y))
        mundo.append((3.6, None))
    return img, mundo


def test_parcial_recupera_a_geometria_da_via():
    img, mundo = _cena_rodovia()
    H = ajustar_homografia(img, mundo, transversais_horizontais=True)
    # distância ao longo da via e largura, em pontos que NÃO entraram no ajuste
    a, b = _pixel(0.0, 50.0), _pixel(0.0, 58.0)
    assert math.dist(aplicar_homografia(H, *a), aplicar_homografia(H, *b)) == pytest.approx(8.0, rel=1e-4)
    esq, dir_ = _pixel(-3.6, 12.0), _pixel(3.6, 12.0)
    assert math.dist(aplicar_homografia(H, *esq), aplicar_homografia(H, *dir_)) == pytest.approx(7.2, rel=1e-4)
    assert max(erros_reprojecao(H, img, mundo)) < 1e-5


def test_parcial_com_ruido_de_pixel_ainda_mede_o_traco():
    img, mundo = _cena_rodovia()
    rng = np.random.default_rng(7)
    img_ruido = [(x + rng.normal(0, 0.7), y + rng.normal(0, 0.7)) for x, y in img]
    H = ajustar_homografia(img_ruido, mundo, transversais_horizontais=True)
    a, b = _pixel(0.0, 20.0), _pixel(0.0, 24.0)
    medida, erro = validar_distancia(H, a, b, 4.0)
    assert abs(erro) < 15.0


def test_parcial_pontos_so_no_eixo_sao_colineares():
    img = [_pixel(0.0, Y) for Y in (0, 4, 16, 20, 32, 36)]
    mundo = [(0.0, Y) for Y in (0, 4, 16, 20, 32, 36)]
    with pytest.raises(ValueError):
        homografia_minimos_quadrados(img, mundo)


def test_parcial_sem_nenhuma_coordenada_longitudinal_levanta_erro():
    img, _ = _cena_rodovia()
    mundo = [(0.0, None)] * 6 + [(-3.6, None)] * 3 + [(3.6, None)] * 3
    with pytest.raises(ValueError):
        homografia_minimos_quadrados(img[:12], mundo)


def test_parcial_poucas_equacoes_levanta_erro():
    img, mundo = _cena_rodovia()
    with pytest.raises(ValueError, match="restrições"):
        homografia_minimos_quadrados(img[:4], [(0.0, None)] * 4)


def test_erro_de_reprojecao_ignora_a_coordenada_desconhecida():
    img, mundo = _cena_rodovia()
    H = ajustar_homografia(img, mundo, transversais_horizontais=True)
    erros = erros_reprojecao(H, [img[7]], [(-3.6 + 0.5, None)])  # 0,5 m de erro só no X
    assert erros[0] == pytest.approx(0.5, abs=1e-3)


def test_completar_mundo_preenche_so_o_que_falta():
    img, mundo = _cena_rodovia()
    H = ajustar_homografia(img, mundo, transversais_horizontais=True)
    completo = completar_mundo(H, img, mundo)
    assert all(X is not None and Y is not None for X, Y in completo)
    assert completo[0] == mundo[0]
    assert completo[6][0] == -3.6
    assert completo[6][1] == pytest.approx(8.0, abs=1e-4)  # Y reconstruído pela homografia


def test_csv_coordenada_em_branco_vira_restricao_parcial(tmp_path):
    arq = tmp_path / "p.csv"
    arq.write_text("nome;px;py;x_m;y_m\nA;1;2;0;5\nB;3;4;-3,6;\nC;5;6;;12\n", encoding="utf-8")
    dados = carregar_pontos(str(arq))
    assert dados["pontos_mundo_m"] == [(0.0, 5.0), (-3.6, None), (None, 12.0)]


def test_csv_ponto_sem_nenhuma_coordenada_em_metros_pede_preenchimento(tmp_path):
    arq = tmp_path / "p.csv"
    arq.write_text("nome;px;py;x_m;y_m\nA;1;2;0;5\nB;3;4;;\n", encoding="utf-8")
    with pytest.raises(ValueError, match="B"):
        carregar_pontos(str(arq))


def test_csv_latlon_com_so_uma_coordenada_pede_preenchimento(tmp_path):
    arq = tmp_path / "p.csv"
    arq.write_text("nome;px;py;lat;lon\nA;1;2;-27,0;\n", encoding="utf-8")
    with pytest.raises(ValueError, match="A"):
        carregar_pontos(str(arq))


def test_main_com_parciais_salva_json_numerico(tmp_path, capsys):
    img, mundo = _cena_rodovia()
    linhas = ["nome;px;py;x_m;y_m"]
    for i, ((px, py), (X, Y)) in enumerate(zip(img, mundo), start=1):
        linhas.append(f"P{i};{px:.4f};{py:.4f};{X};{'' if Y is None else Y}")
    arq = tmp_path / "p.csv"
    arq.write_text("\n".join(linhas), encoding="utf-8")
    saida = tmp_path / "c.json"
    a, b = _pixel(0.0, 50.0), _pixel(0.0, 58.0)
    codigo = main(["--pontos", str(arq), "--resolucao", "576x1024", "--saida", str(saida),
                   "--transversais-horizontais",
                   "--validacao", f"{a[0]:.3f},{a[1]:.3f},{b[0]:.3f},{b[1]:.3f},8.0"])
    texto = capsys.readouterr().out
    assert codigo == 0
    assert "restrição parcial" in texto and "BOA" in texto
    H, resolucao = carregar_calibracao(str(saida))
    assert resolucao == (576, 1024)
    import json
    bloco = json.loads(saida.read_text(encoding="utf-8"))["homografia"]
    assert all(v is not None for ponto in bloco["pontos_mundo_m"] for v in ponto)


def test_sem_a_hipotese_os_pontos_parciais_nao_bastam_e_o_erro_orienta():
    img, mundo = _cena_rodovia()
    with pytest.raises(ValueError, match="transversais-horizontais"):
        ajustar_homografia(img, mundo, transversais_horizontais=False)


def test_pontos_transversais_ficam_na_mesma_linha_da_imagem_do_ponto_de_origem():
    img, mundo = _cena_rodovia()
    novos_img, novos_mundo = pontos_transversais_horizontais(img, mundo)
    assert len(novos_img) == 6 * 2                      # 6 pontos de eixo x 2 linhas de borda
    for (u, v), (X, Y) in zip(novos_img, novos_mundo):
        assert X in (-3.6, 3.6)
        esperado = _pixel(X, Y)                          # nesta cena sintética as linhas transversais são horizontais
        assert (u, v) == pytest.approx(esperado, abs=1e-3)


def test_pontos_transversais_exigem_duas_marcas_por_linha_de_borda():
    img = [_pixel(0.0, 0.0), _pixel(0.0, 4.0), _pixel(-3.6, 8.0)]
    mundo = [(0.0, 0.0), (0.0, 4.0), (-3.6, None)]
    assert pontos_transversais_horizontais(img, mundo) == ([], [])


def test_transversais_horizontais_ruidoso_com_roll_pequeno_mantem_erro_moderado():
    """Se a câmera tiver ~1,5 grau de inclinação lateral, a hipótese erra pouco na medida do traço."""
    img, mundo = _cena_rodovia()
    ang = math.radians(1.5)
    cx, cy = 288.0, 512.0
    girado = [(cx + (u - cx) * math.cos(ang) - (v - cy) * math.sin(ang),
               cy + (u - cx) * math.sin(ang) + (v - cy) * math.cos(ang)) for u, v in img]
    H = ajustar_homografia(girado, mundo, transversais_horizontais=True)
    a, b = _pixel(0.0, 20.0), _pixel(0.0, 24.0)
    a = (cx + (a[0] - cx) * math.cos(ang) - (a[1] - cy) * math.sin(ang), cy + (a[0] - cx) * math.sin(ang) + (a[1] - cy) * math.cos(ang))
    b = (cx + (b[0] - cx) * math.cos(ang) - (b[1] - cy) * math.sin(ang), cy + (b[0] - cx) * math.sin(ang) + (b[1] - cy) * math.cos(ang))
    medida, erro = validar_distancia(H, a, b, 4.0)
    assert abs(erro) < 25.0
