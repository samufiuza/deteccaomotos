"""
Ferramenta de apoio: extrai um frame do vídeo e deixa você marcar, clicando
com o mouse, os pontos de calibração de distância e os polígonos das zonas
de risco — sem precisar advinhar coordenadas.

Uso:
    python ferramenta_calibracao.py --source vídeo_moto.mp4 --frame 100

    --frame: qual frame do vídeo extrair para marcar (padrão: 0, o primeiro).
             Escolha um frame onde a via esteja bem visível, sem veículos
             tampando os pontos que você quer marcar.

Controles na janela que abre:
    Clique esquerdo   -> marca um ponto (aparece um círculo + coordenadas)
    'c'               -> modo CALIBRAÇÃO: clique 2 pontos, depois digite no
                          terminal a distância real (em metros) entre eles
    'z'               -> modo ZONA: clique 3+ pontos formando um polígono,
                          pressione 'n' para fechar a zona atual e nomeá-la,
                          repita para outra zona
    'q'               -> sair e salvar tudo em calibracao_resultado.json,
                          mostrando também o comando pronto para o main.py
    'r'               -> reinicia (apaga os pontos marcados até agora)

Ao sair, o script imprime o comando --calib-p1/--calib-p2/--calib-dist/--zonas
já pronto para copiar e colar.
"""

import argparse
import json

import cv2

pontos_calibracao = []  # até 2 pontos: [(x,y), (x,y)]
zonas = []  # lista de {"nome": str, "poligono": [(x,y), ...]}
poligono_atual = []
modo = None  # None | "calibracao" | "zona"


def extrair_frame(source, indice_frame):
    cap = cv2.VideoCapture(source)
    cap.set(cv2.CAP_PROP_POS_FRAMES, indice_frame)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        raise RuntimeError(f"Não foi possível ler o frame {indice_frame} de {source}")
    return frame


def redesenhar(frame_base):
    frame = frame_base.copy()

    for i, (x, y) in enumerate(pontos_calibracao):
        cv2.circle(frame, (x, y), 6, (0, 255, 255), -1)
        cv2.putText(frame, f"calib{i+1} ({x},{y})", (x + 8, y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

    for zona in zonas:
        pts = zona["poligono"]
        for i in range(len(pts)):
            cv2.line(frame, pts[i], pts[(i + 1) % len(pts)], (0, 0, 255), 2)
        cv2.putText(frame, zona["nome"], pts[0], cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    for i, (x, y) in enumerate(poligono_atual):
        cv2.circle(frame, (x, y), 5, (255, 0, 255), -1)
        cv2.putText(frame, f"({x},{y})", (x + 8, y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 0, 255), 1)

    texto_modo = f"Modo: {modo or 'nenhum (pressione c ou z)'}"
    cv2.putText(frame, texto_modo, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return frame


def clique(event, x, y, flags, param):
    global modo
    if event != cv2.EVENT_LBUTTONDOWN:
        return

    if modo == "calibracao":
        if len(pontos_calibracao) < 2:
            pontos_calibracao.append((x, y))
            print(f"Ponto de calibração marcado: ({x}, {y})")
        if len(pontos_calibracao) == 2:
            print("2 pontos marcados. Pressione 'q' para finalizar, ou 'r' para refazer.")

    elif modo == "zona":
        poligono_atual.append((x, y))
        print(f"Ponto da zona marcado: ({x}, {y}) — pressione 'n' quando terminar esta zona")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Vídeo ou imagem para extrair o frame")
    parser.add_argument("--frame", type=int, default=0, help="Índice do frame a extrair (vídeo)")
    parser.add_argument("--saida", default="calibracao_resultado.json")
    args = parser.parse_args()

    global modo

    if args.source.lower().endswith((".jpg", ".jpeg", ".png")):
        frame_base = cv2.imread(args.source)
    else:
        frame_base = extrair_frame(args.source, args.frame)

    cv2.namedWindow("Calibração")
    cv2.setMouseCallback("Calibração", clique)

    print(__doc__)

    while True:
        cv2.imshow("Calibração", redesenhar(frame_base))
        tecla = cv2.waitKey(20) & 0xFF

        if tecla == ord("c"):
            modo = "calibracao"
            pontos_calibracao.clear()
            print("Modo CALIBRAÇÃO: clique 2 pontos com distância real conhecida.")

        elif tecla == ord("z"):
            modo = "zona"
            poligono_atual.clear()
            print("Modo ZONA: clique os pontos do polígono, depois 'n' para fechar.")

        elif tecla == ord("n") and modo == "zona" and len(poligono_atual) >= 3:
            nome = input("Nome desta zona (ex.: cruzamento, faixa_pedestre): ").strip() or f"zona_{len(zonas)+1}"
            zonas.append({"nome": nome, "poligono": list(poligono_atual)})
            print(f"Zona '{nome}' salva com {len(poligono_atual)} pontos.")
            poligono_atual.clear()

        elif tecla == ord("r"):
            pontos_calibracao.clear()
            poligono_atual.clear()
            print("Pontos reiniciados (zonas já fechadas permanecem).")

        elif tecla == ord("q"):
            break

    cv2.destroyAllWindows()

    resultado = {"zonas": zonas}
    comando_partes = []

    if len(pontos_calibracao) == 2:
        distancia = input(
            f"Distância real (em metros) entre {pontos_calibracao[0]} e {pontos_calibracao[1]}: "
        ).strip()
        p1 = f"{pontos_calibracao[0][0]},{pontos_calibracao[0][1]}"
        p2 = f"{pontos_calibracao[1][0]},{pontos_calibracao[1][1]}"
        resultado["calibracao"] = {"p1": p1, "p2": p2, "distancia_m": distancia}
        comando_partes.append(f'--calib-p1 "{p1}" --calib-p2 "{p2}" --calib-dist {distancia}')

    if zonas:
        with open(args.saida, "w", encoding="utf-8") as f:
            json.dump({"zonas": zonas}, f, indent=2, ensure_ascii=False)
        comando_partes.append(f"--zonas {args.saida}")
        print(f"\n✅ Zonas salvas em {args.saida}")

    print("\n=== COMANDO PRONTO PARA O main.py ===")
    print(f"python main.py --source {args.source} " + " ".join(comando_partes))


if __name__ == "__main__":
    main()
