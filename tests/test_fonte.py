from datetime import datetime, timedelta

import pytest

from fonte import eh_fonte_ao_vivo, nome_origem, timestamp_do_quadro, fps_valido, TAMANHO_MAX_ORIGEM

INICIO = datetime(2026, 10, 5, 14, 0, 0)


# ---- tempo do quadro ----

def test_arquivo_usa_tempo_do_video():
    assert timestamp_do_quadro(0, 30, INICIO, ao_vivo=False) == INICIO
    assert timestamp_do_quadro(30, 30, INICIO, ao_vivo=False) == INICIO + timedelta(seconds=1)
    assert timestamp_do_quadro(45, 30, INICIO, ao_vivo=False) == INICIO + timedelta(seconds=1.5)


def test_arquivo_ignora_relogio_mesmo_com_processamento_lento():
    # cenário do teste do congestionamento: vídeo 30 fps processado a ~2,3 fps.
    # 2 quadros seguidos devem ficar a 1/30 s, não a ~0,44 s do relógio
    t1 = timestamp_do_quadro(100, 30, INICIO, ao_vivo=False, agora=INICIO + timedelta(seconds=44))
    t2 = timestamp_do_quadro(101, 30, INICIO, ao_vivo=False, agora=INICIO + timedelta(seconds=44.44))
    assert (t2 - t1).total_seconds() == pytest.approx(1 / 30, abs=1e-5)


def test_ao_vivo_usa_relogio():
    agora = datetime(2026, 10, 5, 15, 30, 0)
    assert timestamp_do_quadro(999, 30, INICIO, ao_vivo=True, agora=agora) == agora


def test_ao_vivo_sem_agora_usa_datetime_now():
    antes = datetime.now()
    ts = timestamp_do_quadro(0, None, INICIO, ao_vivo=True)
    assert antes <= ts <= datetime.now()


def test_arquivo_com_fps_invalido_levanta_erro():
    with pytest.raises(ValueError):
        timestamp_do_quadro(10, 0, INICIO, ao_vivo=False)


def test_fps_valido():
    assert fps_valido(29.97)
    assert not fps_valido(0)
    assert not fps_valido(float("nan"))
    assert not fps_valido(None)


def test_fonte_ao_vivo():
    assert eh_fonte_ao_vivo(0)
    assert eh_fonte_ao_vivo("1")
    assert eh_fonte_ao_vivo("rtsp://camera.local/stream")
    assert not eh_fonte_ao_vivo("videos/congestionamento.mp4")
    assert not eh_fonte_ao_vivo(r"C:\Users\x\OneDrive\vídeo_moto.mp4")


# ---- nome da origem ----

def test_origem_informada_tem_prioridade():
    assert nome_origem("a/b/c.mp4", "Congestionamento Av. X") == "Congestionamento Av. X"


def test_origem_padrao_e_nome_do_arquivo_sem_pasta():
    assert nome_origem(r"C:\Users\USER\OneDrive\Documentos\DEV\TCC\vídeo_moto.mp4") == "vídeo_moto.mp4"
    assert nome_origem("/home/x/videos/transito.mp4") == "transito.mp4"


def test_origem_webcam():
    assert nome_origem(0) == "webcam_0"


def test_origem_stream_nao_guarda_senha():
    nome = nome_origem("rtsp://admin:senha123@192.168.0.10:554/live")
    assert "senha123" not in nome and "admin" not in nome
    assert nome == "rtsp://192.168.0.10:554/live"


def test_origem_limitada_a_255():
    caminho = "C:/" + "pasta_muito_longa/" * 30 + "x" * 300 + ".mp4"
    assert len(nome_origem(caminho)) == TAMANHO_MAX_ORIGEM
    assert len(nome_origem("v.mp4", "n" * 400)) == TAMANHO_MAX_ORIGEM


def test_origem_em_branco_cai_no_padrao():
    assert nome_origem("dir/v.mp4", "   ") == "v.mp4"
