"""
Pipeline consolidado — Detecção + Tracking + Velocidade + Distância +
Zona de risco + Tendência (mudança brusca / aproximação rápida) + Score +
Persistência.

Uso:
    python main.py --source caminho/para/video.mp4
    python main.py --source caminho/para/video.mp4 --origem "congestionamento_av_x"
    python main.py --source video.mp4 --calib-arquivo calibracao_resultado.json   # homografia
    python main.py --source caminho/para/imagem.jpg
    python main.py --source 0              # webcam
    python main.py --source video.mp4 --no-display   # sem abrir janela (ex.: servidor)

Fechar a janela: tecla 'q' ou o botão X da janela.

Antes de rodar, defina as variáveis de ambiente do banco (ver config.py):
    export DB_HOST=localhost
    export DB_NAME=projeto_motos
    export DB_USER=postgres
    export DB_PASSWORD=sua_senha
"""

import argparse
import json
from collections import defaultdict, deque
from datetime import datetime

import cv2
import numpy as np

import db
from detector import carregar_modelo, detectar_e_rastrear
from calibration import parse_calibracao, carregar_calibracao, reescalar_homografia, projetar_objetos
from fonte import eh_fonte_ao_vivo, nome_origem, fps_valido, timestamp_do_quadro
from state import (
    atualizar_historico_e_calcular,
    atualizar_zonas,
    calcular_riscos,
    calcular_tendencias,
    atualizar_presenca_motos,
)
from config import HISTORICO_MAX_POSICOES, MIN_FRAMES_PRESENCA_MOTO, FPS_PADRAO

JANELA_VIDEO = "Deteccao - Video/Webcam"
JANELA_IMAGEM = "Deteccao - Imagem"


def is_image_file(path):
    return isinstance(path, str) and path.lower().endswith((".jpg", ".jpeg", ".png"))


def carregar_zonas(caminho_json):
    """Lê o arquivo de zonas (ver zonas_exemplo.json). Retorna [] se não informado."""
    if not caminho_json:
        return []
    with open(caminho_json, "r", encoding="utf-8") as f:
        dados = json.load(f)
    # json guarda listas de listas; checar_zona espera tuplas, mas listas também funcionam
    return dados["zonas"]


def parse_args():
    parser = argparse.ArgumentParser(description="Detecção e rastreamento de motos no trânsito")
    parser.add_argument(
        "--source", required=True,
        help="Caminho do vídeo/imagem, '0' para webcam, ou URL rtsp/http de câmera"
    )
    parser.add_argument(
        "--origem", default=None,
        help="Nome amigável do vídeo/câmera salvo no banco e usado no filtro do dashboard "
             "(padrão: nome do arquivo, sem a pasta). Máx. 255 caracteres."
    )
    parser.add_argument(
        "--no-display", action="store_true",
        help="Não abrir janela (necessário em ambientes sem tela)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=30,
        help="Quantidade de registros acumulados antes de salvar no banco (padrão: 30)"
    )
    parser.add_argument(
        "--calib-p1", default=None,
        help='Ponto 1 de calibração na imagem, formato "x,y" (ex.: "100,400")'
    )
    parser.add_argument(
        "--calib-p2", default=None,
        help='Ponto 2 de calibração na imagem, formato "x,y"'
    )
    parser.add_argument(
        "--calib-dist", default=None,
        help="Distância real, em metros, entre os pontos --calib-p1 e --calib-p2"
    )
    parser.add_argument(
        "--calib-arquivo", default=None,
        help="JSON de calibração por homografia (gerado pela ferramenta_calibracao, tecla h). "
             "Tem prioridade sobre --calib-p1/--calib-p2/--calib-dist"
    )
    parser.add_argument(
        "--zonas", default=None,
        help="Caminho para o JSON de zonas de risco (ver zonas_exemplo.json)"
    )
    args = parser.parse_args()

    # "0" vindo da linha de comando deve virar webcam (int), não string
    source = int(args.source) if args.source.strip().isdigit() else args.source
    escala = parse_calibracao(args.calib_p1, args.calib_p2, args.calib_dist)
    calib_chao = None
    if args.calib_arquivo:
        try:
            calib_chao = carregar_calibracao(args.calib_arquivo)
        except (OSError, ValueError) as e:
            parser.error(f"Calibração por homografia inválida: {e}")
        if escala is not None:
            print("ℹ️  --calib-arquivo informado: a calibração por homografia tem prioridade "
                  "sobre --calib-p1/--calib-p2/--calib-dist.")
        print("✅ Calibração por homografia carregada (velocidade e distância no plano do chão).")
    elif escala is None:
        print("⚠️  Sem calibração (--calib-arquivo ou --calib-p1/--calib-p2/--calib-dist não "
              "informados). Velocidade e tendência (mudança brusca/aproximação rápida) não serão "
              "calculadas; distância ficará em pixels.")
    zonas = carregar_zonas(args.zonas)
    if not zonas:
        print("⚠️  Sem zonas de risco configuradas (--zonas não informado).")
    origem = nome_origem(source, args.origem)
    if args.origem and len(args.origem.strip()) > len(origem):
        print(f"⚠️  --origem tinha mais de {len(origem)} caracteres e foi cortado.")
    print(f"🎥 Origem registrada no banco: {origem}")
    return source, origem, args.no_display, args.batch_size, escala, zonas, calib_chao


CORES_NIVEL = {
    "baixo": (0, 200, 0),
    "medio": (0, 165, 255),
    "alto": (0, 0, 255),
}


def janela_fechada(nome):
    """True se o usuário fechou a janela pelo botão X."""
    try:
        return cv2.getWindowProperty(nome, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return True  # janela já destruída


def desenhar(frame, objetos, velocidades, zonas_atuais, zonas, analises, total_motos):
    analises_por_track = {a["track_id"]: a for a in analises}

    # zonas de risco (desenhadas primeiro, ficam "atrás" dos veículos)
    for zona in zonas:
        pts = np.array([(int(x), int(y)) for x, y in zona["poligono"]])
        cv2.polylines(frame, [pts], True, (0, 0, 255), 2)
        cv2.putText(frame, zona["nome"], tuple(int(v) for v in pts[0]),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    for obj in objetos:
        x1, y1, x2, y2 = map(int, obj["bbox"])
        analise = analises_por_track.get(obj["track_id"])
        nivel = analise["risk_level"] if analise else "baixo"
        cor = CORES_NIVEL.get(nivel, (0, 255, 0))

        cv2.rectangle(frame, (x1, y1), (x2, y2), cor, 2)
        label = f'{obj["vehicle_type"]} {obj["confidence"]:.2f}'
        if obj["track_id"] is not None:
            label += f' #{obj["track_id"]}'
        vel = velocidades.get(obj["track_id"])
        if vel is not None:
            label += f' {vel:.0f}km/h'
        if analise:
            label += f' [{analise["risk_score"]}-{nivel}]'
        cv2.putText(frame, label, (x1, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, cor, 2)

    cv2.putText(frame, f"Motos rastreadas: {total_motos}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
    return frame


def novo_estado():
    """Tudo que precisa persistir entre quadros do mesmo vídeo."""
    return {
        "contagem_frames_motos": defaultdict(int),
        "historico": defaultdict(lambda: deque(maxlen=HISTORICO_MAX_POSICOES)),
        "historico_distancias": defaultdict(lambda: deque(maxlen=HISTORICO_MAX_POSICOES)),
        "zona_por_track": {},
        "condicoes": {},
    }


def preparar_homografia(calib_chao, frame):
    """
    Ajusta a homografia carregada à resolução real do vídeo (chamada uma vez,
    no primeiro quadro). Retorna H (numpy 3x3) ou None se não houver
    calibração por homografia. Levanta ValueError se a proporção da imagem
    mudou em relação à da calibração (nesse caso é preciso recalibrar).
    """
    if calib_chao is None:
        return None
    H, resolucao_calib = calib_chao
    altura, largura = frame.shape[:2]
    if (largura, altura) != tuple(resolucao_calib):
        print(f"ℹ️  Resolução do vídeo ({largura}x{altura}) difere da calibração "
              f"({resolucao_calib[0]}x{resolucao_calib[1]}); ajustando a homografia.")
        H = reescalar_homografia(H, resolucao_calib, (largura, altura))
    return H


def processar_frame(frame, model, ts, estado, escala, zonas, H_chao=None):
    """
    Processa um quadro. `ts` é o tempo do quadro (tempo do vídeo em arquivos,
    relógio ao vivo em webcam/stream — ver fonte.timestamp_do_quadro).

    H_chao: homografia (imagem -> plano do chão, em metros) já ajustada à
    resolução do vídeo (ver preparar_homografia), ou None. Com ela, a posição
    de cada veículo é a do ponto de contato com o chão, em metros (mx, my), e
    velocidade, distância e tendência passam a ser medidas no plano do chão;
    sem ela, valem pixels + escala, como antes.
    """
    objetos, _ = detectar_e_rastrear(frame, model)

    # no plano do chão o histórico guarda metros, então a escala efetiva é 1,0
    escala_calculo = escala
    if H_chao is not None:
        projetar_objetos(objetos, H_chao)
        escala_calculo = 1.0

    vizinhos = {}
    velocidades, distancias = atualizar_historico_e_calcular(
        objetos, estado["historico"], escala, ts, vizinhos,
        usar_plano_chao=H_chao is not None,
    )
    tendencias = calcular_tendencias(
        objetos, estado["historico"], distancias, vizinhos,
        estado["historico_distancias"], escala_calculo, ts,
    )
    zonas_atuais, entradas_zona = atualizar_zonas(objetos, zonas, estado["zona_por_track"], ts)
    analises, entradas_condicoes = calcular_riscos(
        objetos, velocidades, distancias, zonas_atuais, estado["condicoes"], tendencias, ts
    )
    entradas = entradas_zona + entradas_condicoes

    # completa velocidade/distância nos eventos de entrada em zona (calcular_riscos
    # já preenche isso para os demais eventos)
    for evento in entradas_zona:
        evento["speed_estimated"] = velocidades.get(evento["track_id"])
        evento["distance"] = distancias.get(evento["track_id"])

    registros = [
        {
            "timestamp": ts,
            "track_id": obj["track_id"],
            "vehicle_type": obj["vehicle_type"],
            "confidence": obj["confidence"],
            "x": obj["x"],
            "y": obj["y"],
            "speed_estimated": velocidades.get(obj["track_id"]),
            "nearest_distance": distancias.get(obj["track_id"]),
        }
        for obj in objetos
    ]

    # só conta como "moto confirmada" quem já apareceu MIN_FRAMES_PRESENCA_MOTO
    # vezes — sem isso, ruído de 1 quadro (falso positivo / troca de ID) infla a contagem
    motos_confirmadas = atualizar_presenca_motos(
        objetos, estado["contagem_frames_motos"], MIN_FRAMES_PRESENCA_MOTO
    )

    return objetos, registros, velocidades, zonas_atuais, entradas, analises, motos_confirmadas


def main():
    source, origem, no_display, batch_size, escala, zonas, calib_chao = parse_args()

    conn = db.conectar()
    db.garantir_schema(conn)
    print("✅ Conexão com o banco realizada e schema garantido.")

    model = carregar_modelo()

    estado = novo_estado()
    motos_confirmadas = set()
    buffers = {"registros": [], "eventos": [], "analises": []}

    def salvar(forcar=False):
        if buffers["registros"] and (forcar or len(buffers["registros"]) >= batch_size):
            db.salvar_deteccoes(conn, origem, buffers["registros"])
            buffers["registros"] = []
        if buffers["eventos"]:
            db.salvar_eventos(conn, buffers["eventos"], origem)
            buffers["eventos"] = []
        if buffers["analises"] and (forcar or len(buffers["analises"]) >= batch_size):
            db.salvar_analises_risco(conn, buffers["analises"], origem)
            buffers["analises"] = []

    def acumular(registros, entradas, analises):
        buffers["registros"].extend(registros)
        buffers["eventos"].extend(entradas)
        buffers["analises"].extend(analises)

    try:
        if is_image_file(source):
            frame = cv2.imread(source)
            if frame is None:
                print("❌ Erro: imagem não encontrada.")
                return
            try:
                H_chao = preparar_homografia(calib_chao, frame)
            except ValueError as e:
                print(f"❌ {e}")
                return
            objetos, registros, velocidades, zonas_atuais, entradas, analises, motos_confirmadas = \
                processar_frame(frame, model, datetime.now(), estado, escala, zonas, H_chao=H_chao)
            acumular(registros, entradas, analises)
            frame = desenhar(frame, objetos, velocidades, zonas_atuais, zonas, analises, len(motos_confirmadas))
            if not no_display:
                cv2.imshow(JANELA_IMAGEM, frame)
                # espera 'q'/ESC ou o X da janela (waitKey(0) sozinho ignora o X)
                while True:
                    tecla = cv2.waitKey(100) & 0xFF
                    if tecla in (ord("q"), 27) or janela_fechada(JANELA_IMAGEM):
                        break
                cv2.destroyAllWindows()
        else:
            cap = cv2.VideoCapture(source)
            if not cap.isOpened():
                print("❌ Erro ao abrir vídeo/webcam.")
                return

            ao_vivo = eh_fonte_ao_vivo(source)
            fps = cap.get(cv2.CAP_PROP_FPS)
            if ao_vivo:
                print("⏱️  Fonte ao vivo: tempo de cada quadro = relógio do computador.")
            else:
                if not fps_valido(fps):
                    print(f"⚠️  O arquivo não informa FPS; usando FPS_PADRAO={FPS_PADRAO}.")
                    fps = FPS_PADRAO
                print(f"⏱️  Arquivo de vídeo: tempo de cada quadro = quadro ÷ {fps:.2f} fps "
                      "(independe da velocidade de processamento).")
            inicio = datetime.now()

            indice_quadro = 0
            H_chao = None
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if indice_quadro == 0:
                    try:
                        H_chao = preparar_homografia(calib_chao, frame)
                    except ValueError as e:
                        print(f"❌ {e}")
                        break

                ts = timestamp_do_quadro(indice_quadro, fps, inicio, ao_vivo)
                objetos, registros, velocidades, zonas_atuais, entradas, analises, motos_confirmadas = \
                    processar_frame(frame, model, ts, estado, escala, zonas, H_chao=H_chao)
                acumular(registros, entradas, analises)
                indice_quadro += 1

                if not no_display:
                    frame = desenhar(frame, objetos, velocidades, zonas_atuais, zonas, analises,
                                     len(motos_confirmadas))
                    cv2.imshow(JANELA_VIDEO, frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                    if janela_fechada(JANELA_VIDEO):  # botão X
                        break

                salvar()

            cap.release()
            if not no_display:
                cv2.destroyAllWindows()

        salvar(forcar=True)  # flush final

        print(f"💾 Total de motos confirmadas (>= {MIN_FRAMES_PRESENCA_MOTO} quadros de presença): "
              f"{len(motos_confirmadas)}")

    finally:
        conn.close()
        print("Conexão com o banco encerrada.")


if __name__ == "__main__":
    main()
