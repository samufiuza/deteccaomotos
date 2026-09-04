from collections import defaultdict

from state import atualizar_presenca_motos

MIN_FRAMES = 3


def _contagem():
    return defaultdict(int)


def test_moto_com_1_frame_nao_e_confirmada():
    contagem = _contagem()
    confirmadas = atualizar_presenca_motos(
        [{"track_id": 1, "vehicle_type": "motorcycle"}], contagem, MIN_FRAMES
    )
    assert confirmadas == set()


def test_moto_atinge_limiar_e_confirmada():
    contagem = _contagem()
    for _ in range(MIN_FRAMES):
        confirmadas = atualizar_presenca_motos(
            [{"track_id": 1, "vehicle_type": "motorcycle"}], contagem, MIN_FRAMES
        )
    assert confirmadas == {1}


def test_moto_abaixo_do_limiar_ainda_nao_confirmada():
    contagem = _contagem()
    for _ in range(MIN_FRAMES - 1):
        confirmadas = atualizar_presenca_motos(
            [{"track_id": 1, "vehicle_type": "motorcycle"}], contagem, MIN_FRAMES
        )
    assert confirmadas == set()


def test_carro_nunca_e_contado_mesmo_com_muitos_frames():
    contagem = _contagem()
    for _ in range(10):
        confirmadas = atualizar_presenca_motos(
            [{"track_id": 1, "vehicle_type": "car"}], contagem, MIN_FRAMES
        )
    assert confirmadas == set()


def test_track_id_none_e_ignorado():
    contagem = _contagem()
    confirmadas = atualizar_presenca_motos(
        [{"track_id": None, "vehicle_type": "motorcycle"}], contagem, MIN_FRAMES
    )
    assert confirmadas == set()


def test_multiplas_motos_confirmadas_independentemente():
    contagem = _contagem()
    # moto 1: aparece o suficiente; moto 2: aparece só 1 vez (ruído)
    for _ in range(MIN_FRAMES):
        confirmadas = atualizar_presenca_motos(
            [{"track_id": 1, "vehicle_type": "motorcycle"}], contagem, MIN_FRAMES
        )
    confirmadas = atualizar_presenca_motos(
        [{"track_id": 2, "vehicle_type": "motorcycle"}], contagem, MIN_FRAMES
    )
    assert confirmadas == {1}  # moto 2 ainda não atingiu o limiar


def test_reflete_cenario_real_do_video_de_teste():
    # reproduz o padrão observado no teste com vídeo real: alguns IDs sólidos
    # (>=100 frames) e alguns IDs de ruído (1 frame só)
    contagem = _contagem()
    presencas_reais = {17: 122, 74: 1, 140: 1, 146: 114, 196: 1}
    for tid, n_frames in presencas_reais.items():
        for _ in range(n_frames):
            confirmadas = atualizar_presenca_motos(
                [{"track_id": tid, "vehicle_type": "motorcycle"}], contagem, MIN_FRAMES
            )
    assert confirmadas == {17, 146}  # só os sólidos ficam; ruído (74,140,196) fica de fora
