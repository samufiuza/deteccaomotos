"""
Fonte de vídeo: nome amigável da origem e tempo de cada quadro.

Separado de main.py (mesmo padrão de state.py) para ser testável sem
OpenCV/YOLO/banco.
"""

import math
import os
from datetime import datetime, timedelta
from urllib.parse import urlsplit

TAMANHO_MAX_ORIGEM = 255  # mesmo tamanho da coluna origem_video (VARCHAR(255))

PREFIXOS_AO_VIVO = ("rtsp://", "rtmp://", "http://", "https://", "udp://", "tcp://")


def eh_fonte_ao_vivo(source):
    """
    True para webcam (int ou "0", "1"...) e streams de rede (rtsp, http...).
    False para arquivos de vídeo/imagem.
    """
    if isinstance(source, int):
        return True
    texto = str(source).strip()
    if texto.isdigit():
        return True
    return texto.lower().startswith(PREFIXOS_AO_VIVO)


def nome_origem(source, origem_informada=None):
    """
    Nome que vai para a coluna origem_video (detecções, eventos e análises).

    - Se o usuário passou --origem, usa esse nome.
    - Webcam: "webcam_<indice>".
    - Stream: só host + caminho (NUNCA usuário/senha que estejam na URL).
    - Arquivo: só o nome do arquivo, sem a pasta (caminhos do OneDrive/Windows
      podem passar fácil de 255 caracteres).

    Sempre limitado a TAMANHO_MAX_ORIGEM caracteres.
    """
    if origem_informada and origem_informada.strip():
        nome = origem_informada.strip()
    elif isinstance(source, int) or str(source).strip().isdigit():
        nome = f"webcam_{int(source)}"
    elif eh_fonte_ao_vivo(source):
        partes = urlsplit(str(source))
        host = partes.hostname or ""
        if partes.port:
            host += f":{partes.port}"
        nome = f"{partes.scheme}://{host}{partes.path}"
    else:
        nome = os.path.basename(str(source).replace("\\", "/")) or str(source)
    return nome[:TAMANHO_MAX_ORIGEM]


def fps_valido(fps):
    return fps is not None and not math.isnan(fps) and fps > 0


def timestamp_do_quadro(indice_quadro, fps, inicio, ao_vivo, agora=None):
    """
    Tempo associado a um quadro.

    - Arquivo de vídeo: inicio + indice_quadro / fps (tempo do VÍDEO). Assim a
      velocidade não depende de quão rápido o computador processa: a 2 FPS de
      processamento em um vídeo de 30 FPS, o relógio da máquina faria cada
      quadro "durar" 0,5 s em vez de 0,033 s e a velocidade sairia ~15x menor.
    - Ao vivo (webcam/stream): relógio da máquina (`agora`, ou datetime.now()).
    """
    if ao_vivo:
        return agora if agora is not None else datetime.now()
    if not fps_valido(fps):
        raise ValueError("fps inválido para calcular o tempo do quadro de um arquivo")
    return inicio + timedelta(seconds=indice_quadro / fps)
