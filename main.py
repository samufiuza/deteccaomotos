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
import json
import os
from collections import defaultdict, deque
from datetime import datetime

import cv2
import numpy as np

import db
from detector import carregar_modelo, detectar_e_rastrear
from calibration import parse_calibracao
from state import atualizar_historico_e_calcular, atualizar_zonas, calcular_riscos
from config import PRIMARY_CLASS_ID, HISTORICO_MAX_POSICOES


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
    parser.add_argument(
        "--zonas", default=None,
        help="Caminho para o JSON de zonas de risco (ver zonas_exemplo.json)"
    )
    args = parser.parse_args()

    # "0" vindo da linha de comando deve virar webcam (int), não string
    source = 0 if args.source == "0" else args.source
    escala = parse_calibracao(args.calib_p1, args.calib_p2, args.calib_dist)
    if escala is None:
        print("⚠️  Sem calibração (--calib-p1/--calib-p2/--calib-dist não informados). "
              "Velocidade não será calculada; distância ficará em pixels.")
    zonas = carregar_zonas(args.zonas)
    if not zonas:
        print("⚠️  Sem zonas de risco configuradas (--zonas não informado).")
    return source, args.no_display, args.batch_size, escala, zonas


CORES_NIVEL = {
    "baixo": (0, 200, 0),
    "medio": (0, 165, 255),
    "alto": (0, 0, 255),
}


def desenhar(frame, objetos, velocidades, zonas_atuais, zonas, analises, total_motos):
    analises_por_track = {a["track_id"]: a for a in analises}

    # zonas de risco (desenhadas primeiro, ficam "atrás" dos veículos)
    for zona in zonas:
        pts = np.array([(int(x), int(y)) for x, y in zona["poligono"]])
        cv2.polylines(frame, [pts], True, (0, 0, 255), 2)
        cv2.putText(frame, zona["nome"], tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

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


def processar_frame(frame, model, motos_rastreadas, historico, escala, zonas, zona_por_track, estado_condicoes):
    objetos, res = detectar_e_rastrear(frame, model)

    ts = datetime.now()
    velocidades, distancias = atualizar_historico_e_calcular(objetos, historico, escala, ts)
    zonas_atuais, entradas_zona = atualizar_zonas(objetos, zonas, zona_por_track)
    analises, entradas_condicoes = calcular_riscos(
        objetos, velocidades, distancias, zonas_atuais, estado_condicoes
    )
    entradas = entradas_zona + entradas_condicoes

    # completa velocidade/distância nos eventos de entrada em zona (calcular_riscos
    # já preenche isso para velocidade_elevada/proximidade_perigosa)
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

    for obj in objetos:
        if obj["vehicle_type"] == "motorcycle" and obj["track_id"] is not None:
            motos_rastreadas.add(obj["track_id"])

    return objetos, registros, velocidades, zonas_atuais, entradas, analises


def main():
    source, no_display, batch_size, escala, zonas = parse_args()

    conn = db.conectar()
    db.garantir_schema(conn)
    print("✅ Conexão com o banco realizada e schema garantido.")

    model = carregar_modelo()

    motos_rastreadas = set()
    buffer_registros = []
    buffer_eventos = []
    buffer_analises = []
    historico = defaultdict(lambda: deque(maxlen=HISTORICO_MAX_POSICOES))
    zona_por_track = {}
    estado_condicoes = {}

    try:
        if is_image_file(source):
            frame = cv2.imread(source)
            if frame is None:
                print("❌ Erro: imagem não encontrada.")
                return
            objetos, registros, velocidades, zonas_atuais, entradas, analises = processar_frame(
                frame, model, motos_rastreadas, historico, escala, zonas, zona_por_track, estado_condicoes
            )
            buffer_registros.extend(registros)
            buffer_eventos.extend(entradas)
            buffer_analises.extend(analises)
            frame = desenhar(frame, objetos, velocidades, zonas_atuais, zonas, analises, len(motos_rastreadas))
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

                objetos, registros, velocidades, zonas_atuais, entradas, analises = processar_frame(
                    frame, model, motos_rastreadas, historico, escala, zonas, zona_por_track, estado_condicoes
                )
                buffer_registros.extend(registros)
                buffer_eventos.extend(entradas)
                buffer_analises.extend(analises)
                frame_count += 1

                if not no_display:
                    frame = desenhar(frame, objetos, velocidades, zonas_atuais, zonas, analises, len(motos_rastreadas))
                    cv2.imshow("Detecção - Vídeo/Webcam", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

                if len(buffer_registros) >= batch_size:
                    db.salvar_deteccoes(conn, str(source), buffer_registros)
                    buffer_registros = []
                if buffer_eventos:
                    db.salvar_eventos(conn, buffer_eventos)
                    buffer_eventos = []
                if buffer_analises:
                    db.salvar_analises_risco(conn, buffer_analises)
                    buffer_analises = []

            cap.release()
            if not no_display:
                cv2.destroyAllWindows()

        # flush final
        if buffer_registros:
            db.salvar_deteccoes(conn, str(source), buffer_registros)
        if buffer_eventos:
            db.salvar_eventos(conn, buffer_eventos)
        if buffer_analises:
            db.salvar_analises_risco(conn, buffer_analises)

        print(f"💾 Total de motos únicas rastreadas: {len(motos_rastreadas)}")

    finally:
        conn.close()
        print("Conexão com o banco encerrada.")


if __name__ == "__main__":
    main()
