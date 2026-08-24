"""
Pipeline consolidado — Etapa atual: Detecção + Tracking + Persistência.

Substitui detectio_motos.py, detection.py e main.py do projeto original,
que faziam a mesma coisa de formas diferentes.

Uso:
    python main.py --source caminho/para/video.mp4
    python main.py --source caminho/para/imagem.jpg
    python main.py --source 0              # webcam
    python main.py --source video.mp4 --no-display   # sem abrir janela (ex.: servidor)

Antes de rodar, defina as variáveis de ambiente do banco (ver config.py):
    export DB_HOST=localhost
    export DB_NAME=projeto_motos
    export DB_USER=postgres
    export DB_PASSWORD=sua_senha
"""

import argparse
import os
from collections import defaultdict, deque
from datetime import datetime

import cv2

import db
from detector import carregar_modelo, detectar_e_rastrear
from calibration import parse_calibracao
from risk import calcular_velocidade, calcular_distancia
from config import PRIMARY_CLASS_ID, HISTORICO_MAX_POSICOES


def is_image_file(path):
    return isinstance(path, str) and path.lower().endswith((".jpg", ".jpeg", ".png"))


def parse_args():
    parser = argparse.ArgumentParser(description="Detecção e rastreamento de motos no trânsito")
    parser.add_argument(
        "--source", required=True,
        help="Caminho do vídeo/imagem, ou '0' para webcam"
    )
    parser.add_argument(
        "--no-display", action="store_true",
        help="Não abrir janela (necessário em ambientes sem tela)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=30,
        help="Quantidade de frames processados antes de salvar no banco (padrão: 30)"
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
    args = parser.parse_args()

    # "0" vindo da linha de comando deve virar webcam (int), não string
    source = 0 if args.source == "0" else args.source
    escala = parse_calibracao(args.calib_p1, args.calib_p2, args.calib_dist)
    if escala is None:
        print("⚠️  Sem calibração (--calib-p1/--calib-p2/--calib-dist não informados). "
              "Velocidade não será calculada; distância ficará em pixels.")
    return source, args.no_display, args.batch_size, escala


def desenhar(frame, objetos, velocidades, total_motos):
    for obj in objetos:
        x1, y1, x2, y2 = map(int, obj["bbox"])
        cor = (0, 255, 0) if obj["vehicle_type"] == "motorcycle" else (255, 180, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), cor, 2)
        label = f'{obj["vehicle_type"]} {obj["confidence"]:.2f}'
        if obj["track_id"] is not None:
            label += f' #{obj["track_id"]}'
        vel = velocidades.get(obj["track_id"])
        if vel is not None:
            label += f' {vel:.0f}km/h'
        cv2.putText(frame, label, (x1, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, cor, 2)

    cv2.putText(frame, f"Motos rastreadas: {total_motos}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
    return frame


def atualizar_historico_e_calcular(objetos, historico, escala, ts):
    """
    Atualiza o histórico de posições por track_id e calcula, para cada
    objeto: velocidade estimada e distância até o veículo mais próximo no
    mesmo frame.

    Retorna (velocidades: {track_id: km/h|None}, distancias: {track_id: metros|pixels|None})
    """
    # 1. Atualizar histórico
    for obj in objetos:
        if obj["track_id"] is None:
            continue
        historico[obj["track_id"]].append({"x": obj["x"], "y": obj["y"], "timestamp": ts})

    # 2. Velocidade por track_id
    velocidades = {}
    for obj in objetos:
        tid = obj["track_id"]
        if tid is None:
            velocidades[tid] = None
            continue
        velocidades[tid] = calcular_velocidade(list(historico[tid]), escala)

    # 3. Distância até o objeto mais próximo, no mesmo frame
    distancias = {}
    for i, obj_a in enumerate(objetos):
        menor = None
        for j, obj_b in enumerate(objetos):
            if i == j:
                continue
            d = calcular_distancia(obj_a, obj_b, escala)
            if menor is None or d < menor:
                menor = d
        distancias[obj_a["track_id"]] = menor

    return velocidades, distancias


def processar_frame(frame, model, motos_rastreadas, historico, escala):
    objetos, res = detectar_e_rastrear(frame, model)

    ts = datetime.now()
    velocidades, distancias = atualizar_historico_e_calcular(objetos, historico, escala, ts)

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

    for obj in objetos:
        if obj["vehicle_type"] == "motorcycle" and obj["track_id"] is not None:
            motos_rastreadas.add(obj["track_id"])

    return objetos, registros, velocidades


def main():
    source, no_display, batch_size, escala = parse_args()

    conn = db.conectar()
    db.garantir_schema(conn)
    print("✅ Conexão com o banco realizada e schema garantido.")

    model = carregar_modelo()

    motos_rastreadas = set()
    buffer_registros = []
    historico = defaultdict(lambda: deque(maxlen=HISTORICO_MAX_POSICOES))

    try:
        if is_image_file(source):
            frame = cv2.imread(source)
            if frame is None:
                print("❌ Erro: imagem não encontrada.")
                return
            objetos, registros, velocidades = processar_frame(
                frame, model, motos_rastreadas, historico, escala
            )
            buffer_registros.extend(registros)
            frame = desenhar(frame, objetos, velocidades, len(motos_rastreadas))
            if not no_display:
                cv2.imshow("Detecção - Imagem", frame)
                cv2.waitKey(0)
                cv2.destroyAllWindows()
        else:
            cap = cv2.VideoCapture(source)
            if not cap.isOpened():
                print("❌ Erro ao abrir vídeo/webcam.")
                return

            frame_count = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                objetos, registros, velocidades = processar_frame(
                    frame, model, motos_rastreadas, historico, escala
                )
                buffer_registros.extend(registros)
                frame_count += 1

                if not no_display:
                    frame = desenhar(frame, objetos, velocidades, len(motos_rastreadas))
                    cv2.imshow("Detecção - Vídeo/Webcam", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

                if len(buffer_registros) >= batch_size:
                    db.salvar_deteccoes(conn, str(source), buffer_registros)
                    buffer_registros = []

            cap.release()
            if not no_display:
                cv2.destroyAllWindows()

        # flush final
        if buffer_registros:
            db.salvar_deteccoes(conn, str(source), buffer_registros)

        print(f"💾 Total de motos únicas rastreadas: {len(motos_rastreadas)}")

    finally:
        conn.close()
        print("Conexão com o banco encerrada.")


if __name__ == "__main__":
    main()
