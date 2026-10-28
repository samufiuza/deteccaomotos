import cv2
import numpy as np
import pytest

from estabilizar_video import (
    descrever_homografia,
    estabilizar,
    estimar_homografia,
    main,
    quadro_valido,
    segmentos_estaveis,
    analisar,
    _criar_orb,
)

LARGURA, ALTURA = 640, 480


def _cena(semente=0):
    """Imagem sintética com bastante textura (para o ORB achar pontos)."""
    rng = np.random.default_rng(semente)
    img = np.full((ALTURA, LARGURA, 3), 120, np.uint8)
    for _ in range(150):
        x, y = int(rng.integers(0, LARGURA)), int(rng.integers(0, ALTURA))
        w, h = int(rng.integers(8, 50)), int(rng.integers(8, 50))
        cor = tuple(int(c) for c in rng.integers(0, 255, 3))
        cv2.rectangle(img, (x, y), (x + w, y + h), cor, -1 if rng.random() < 0.6 else 2)
    for _ in range(60):
        cv2.circle(img, (int(rng.integers(0, LARGURA)), int(rng.integers(0, ALTURA))),
                   int(rng.integers(3, 20)), tuple(int(c) for c in rng.integers(0, 255, 3)), -1)
    return img


def _deslocada(img, dx, dy, escala=1.0, graus=0.0):
    M = cv2.getRotationMatrix2D((LARGURA / 2, ALTURA / 2), graus, escala)
    M[0, 2] += dx
    M[1, 2] += dy
    H = np.vstack([M, [0, 0, 1]])
    return cv2.warpPerspective(img, H, (LARGURA, ALTURA)), H


def _erro_cantos(H_est, H_real_inversa):
    """Erro máximo (px) entre duas homografias nos cantos e no centro da imagem."""
    pts = np.float32([[0, 0], [LARGURA, 0], [LARGURA, ALTURA], [0, ALTURA], [LARGURA / 2, ALTURA / 2]]).reshape(-1, 1, 2)
    a = cv2.perspectiveTransform(pts, H_est)
    b = cv2.perspectiveTransform(pts, H_real_inversa)
    return float(np.max(np.linalg.norm(a - b, axis=2)))


def _referencia(img):
    orb = _criar_orb()
    kp, des = orb.detectAndCompute(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), None)
    return orb, kp, des


# ---- estimativa da homografia ----

def test_recupera_deslocamento_conhecido():
    cv2.setRNGSeed(0)
    ref = _cena()
    atual, H_aplicada = _deslocada(ref, 14.0, -9.0)
    orb, kp, des = _referencia(ref)
    H, inliers = estimar_homografia(kp, des, cv2.cvtColor(atual, cv2.COLOR_BGR2GRAY), orb)
    assert H is not None and inliers > 80
    # H leva do quadro atual de volta à referência: é a inversa do deslocamento aplicado
    # tolerância nos cantos (640x480): o RANSAC é aleatório e muda um pouco entre
    # versões do OpenCV; o erro no centro, que é o que importa, fica bem abaixo disso
    assert _erro_cantos(H, np.linalg.inv(H_aplicada)) < 4.0


def test_recupera_pequena_rotacao_e_escala():
    cv2.setRNGSeed(0)
    ref = _cena(1)
    atual, H_aplicada = _deslocada(ref, 5.0, 3.0, escala=1.02, graus=1.0)
    orb, kp, des = _referencia(ref)
    H, _ = estimar_homografia(kp, des, cv2.cvtColor(atual, cv2.COLOR_BGR2GRAY), orb)
    assert _erro_cantos(H, np.linalg.inv(H_aplicada)) < 4.0


def test_imagem_sem_textura_nao_alinha():
    ref = _cena(2)
    orb, kp, des = _referencia(ref)
    vazio = np.full((ALTURA, LARGURA), 100, np.uint8)
    H, _ = estimar_homografia(kp, des, vazio, orb)
    assert H is None


def test_descrever_homografia_identidade():
    d = descrever_homografia(np.eye(3), LARGURA, ALTURA)
    assert d["dx"] == pytest.approx(0) and d["dy"] == pytest.approx(0)
    assert d["escala"] == pytest.approx(1.0) and d["rotacao"] == pytest.approx(0)


def test_descrever_homografia_deslocamento_e_escala():
    H = np.array([[1.1, 0, 20.0], [0, 1.1, -10.0], [0, 0, 1.0]])
    d = descrever_homografia(H, LARGURA, ALTURA)
    assert d["escala"] == pytest.approx(1.1)
    assert d["dx"] == pytest.approx(1.1 * LARGURA / 2 + 20.0 - LARGURA / 2)
    assert d["dy"] == pytest.approx(1.1 * ALTURA / 2 - 10.0 - ALTURA / 2)


# ---- validade e trechos ----

def test_quadro_valido_aceita_zoom_proximo_e_rejeita_zoom_diferente():
    assert quadro_valido({"escala": 1.01, "rotacao": 0.5})
    assert not quadro_valido({"escala": 0.63, "rotacao": 0.0})
    assert not quadro_valido({"escala": 1.0, "rotacao": 8.0})
    assert not quadro_valido(None)


def test_segmentos_estaveis_separa_trechos_e_descarta_curtos():
    regs = []
    for q, v in [(0, False), (30, True), (60, True), (90, True), (120, True), (150, True), (180, True),
                 (210, False), (240, True), (270, True), (300, False)]:
        regs.append({"quadro": q, "valido": v})
    assert segmentos_estaveis(regs, min_quadros=60) == [(30, 180)]  # o trecho 240-270 é curto demais


def test_segmentos_estaveis_trecho_vai_ate_o_fim():
    regs = [{"quadro": q, "valido": True} for q in range(0, 300, 30)]
    assert segmentos_estaveis(regs, min_quadros=60) == [(0, 270)]


def test_segmentos_estaveis_sem_validos():
    assert segmentos_estaveis([{"quadro": 0, "valido": False}], min_quadros=0) == []


# ---- ponta a ponta com vídeo sintético ----

def _gravar_video_balancando(caminho, n=24):
    ref = _cena(3)
    esc = cv2.VideoWriter(str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (LARGURA, ALTURA))
    for i in range(n):
        quadro, _ = _deslocada(ref, 12.0 * np.sin(i / 3.0), 8.0 * np.cos(i / 4.0))
        esc.write(quadro)
    esc.release()


def test_estabilizar_reduz_o_balanco(tmp_path):
    entrada = tmp_path / "balanca.mp4"
    saida = tmp_path / "estavel.mp4"
    _gravar_video_balancando(entrada)
    ref_jpg = tmp_path / "ref.jpg"
    stats = estabilizar(str(entrada), str(saida), referencia=0, inicio=0, fim=23, caminho_referencia=str(ref_jpg))
    assert stats["escritos"] == 24 and stats["repetidos"] == 0
    assert ref_jpg.exists()

    def deslocamentos(caminho):
        cap = cv2.VideoCapture(str(caminho))
        base, saidas = None, []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)[100:380, 100:540].astype(np.float32)
            if base is None:
                base = g
                continue
            (dx, dy), _ = cv2.phaseCorrelate(base, g)
            saidas.append(max(abs(dx), abs(dy)))
        return max(saidas)

    assert deslocamentos(entrada) > 6.0       # o original balança de verdade
    assert deslocamentos(saida) < 2.0         # o estabilizado quase não se move


def test_estabilizar_intervalo_invalido(tmp_path):
    entrada = tmp_path / "v.mp4"
    _gravar_video_balancando(entrada, n=10)
    with pytest.raises(ValueError):
        estabilizar(str(entrada), str(tmp_path / "s.mp4"), 0, 5, 99)


def test_analisar_e_cli(tmp_path, capsys):
    entrada = tmp_path / "v.mp4"
    _gravar_video_balancando(entrada, n=70)
    res = analisar(str(entrada), referencia=0, passo=10)
    assert res["total"] == 70 and len(res["registros"]) == 7
    assert all(r["valido"] for r in res["registros"])
    codigo = main(["--entrada", str(entrada), "--analisar", "--referencia", "0", "--passo", "10"])
    assert codigo == 0
    assert "Trechos estáveis" in capsys.readouterr().out


def test_cli_estabilizar_sem_argumentos_obrigatorios(tmp_path):
    entrada = tmp_path / "v.mp4"
    _gravar_video_balancando(entrada, n=10)
    assert main(["--entrada", str(entrada), "--saida", str(tmp_path / "s.mp4")]) == 2


def test_cli_arquivo_inexistente(tmp_path, capsys):
    assert main(["--entrada", str(tmp_path / "nao_existe.mp4"), "--analisar"]) == 1
    assert "ERRO" in capsys.readouterr().out
