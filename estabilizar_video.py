"""
Estabilização de vídeo gravado com a câmera na mão (celular).

A calibração por homografia vale para UMA posição de câmera. Num vídeo filmado
na mão a câmera balança, desliza e às vezes muda o zoom, e a calibração feita
num quadro deixa de valer nos outros (um deslocamento de poucos pixels ao fundo
da via vira vários metros). Este script alinha cada quadro ao quadro de
referência, de modo que o vídeo resultante se comporta como se a câmera
estivesse fixa. Calibre, então, no quadro de referência.

Funcionamento: pontos de interesse (ORB) são casados entre cada quadro e o de
referência; uma homografia é ajustada com RANSAC (os veículos em movimento
viram "outliers") e o quadro é deformado para a geometria da referência. Vale
quando a câmera gira ou treme (movimento de rotação) e quando o fundo é plano
ou distante, que é o caso de uma via vista de uma passarela.

Uso:
    # 1) analisar: mostra deslocamento, escala e trechos estáveis
    python estabilizar_video.py --entrada video.mp4 --analisar

    # 2) estabilizar um trecho (quadros inicio..fim) em relação ao quadro de referência
    python estabilizar_video.py --entrada video.mp4 --saida video_est.mp4 \
        --referencia 595 --inicio 180 --fim 680

Gera também <saida>_referencia.jpg (o quadro de referência, para calibrar).
Trechos em que o zoom muda (escala diferente de 1) não devem ser misturados:
use um trecho e uma referência por enquadramento.
"""

import argparse
import math
import sys

import cv2
import numpy as np

N_FEATURES = 3000
LIMIAR_RANSAC_PX = 3.0
MIN_INLIERS = 80
TOLERANCIA_ESCALA = 0.03   # |escala - 1| máxima para o quadro valer na referência
TOLERANCIA_ROTACAO_GRAUS = 3.0


def _criar_orb():
    return cv2.ORB_create(N_FEATURES)


def estimar_homografia(kp_ref, des_ref, quadro_cinza, orb=None, matcher=None,
                       limiar=LIMIAR_RANSAC_PX, min_inliers=MIN_INLIERS):
    """
    Homografia que leva pixels do quadro atual para a geometria da referência.
    Retorna (H, inliers) ou (None, inliers) se não houver correspondências
    suficientes.
    """
    orb = orb or _criar_orb()
    matcher = matcher or cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    kp, des = orb.detectAndCompute(quadro_cinza, None)
    if des is None or des_ref is None or len(kp) < 10:
        return None, 0
    casados = matcher.match(des, des_ref)
    if len(casados) < min_inliers:
        return None, len(casados)
    origem = np.float32([kp[m.queryIdx].pt for m in casados])
    destino = np.float32([kp_ref[m.trainIdx].pt for m in casados])
    H, mascara = cv2.findHomography(origem, destino, cv2.RANSAC, limiar)
    if H is None:
        return None, 0
    inliers = int(mascara.sum())
    if inliers < min_inliers:
        return None, inliers
    return H, inliers


def descrever_homografia(H, largura, altura):
    """Deslocamento do centro (px), escala e rotação (graus) de H."""
    centro = H @ np.array([largura / 2.0, altura / 2.0, 1.0])
    centro = centro[:2] / centro[2]
    A = H[:2, :2] / H[2, 2]
    escala = math.sqrt(abs(np.linalg.det(A)))
    rotacao = math.degrees(math.atan2(A[1, 0], A[0, 0]))
    return {
        "dx": float(centro[0] - largura / 2.0),
        "dy": float(centro[1] - altura / 2.0),
        "escala": float(escala),
        "rotacao": float(rotacao),
    }


def quadro_valido(desc, tol_escala=TOLERANCIA_ESCALA, tol_rotacao=TOLERANCIA_ROTACAO_GRAUS):
    """Um quadro serve para a calibração da referência se o zoom e a rotação quase não mudaram."""
    if desc is None:
        return False
    return abs(desc["escala"] - 1.0) <= tol_escala and abs(desc["rotacao"]) <= tol_rotacao


def segmentos_estaveis(registros, min_quadros=60):
    """
    registros: lista de dicts {"quadro": int, "valido": bool}, em ordem.
    Retorna [(inicio, fim)] dos trechos contíguos válidos com ao menos
    `min_quadros` quadros de duração (do primeiro ao último quadro amostrado).
    """
    trechos, inicio, ultimo = [], None, None
    for r in registros:
        if r["valido"]:
            if inicio is None:
                inicio = r["quadro"]
            ultimo = r["quadro"]
        else:
            if inicio is not None and ultimo - inicio >= min_quadros:
                trechos.append((inicio, ultimo))
            inicio = None
    if inicio is not None and ultimo - inicio >= min_quadros:
        trechos.append((inicio, ultimo))
    return trechos


def _abrir(entrada):
    cap = cv2.VideoCapture(entrada)
    if not cap.isOpened():
        raise ValueError(f"Não consegui abrir o vídeo: {entrada}")
    return cap


def _ler_quadro(cap, indice):
    cap.set(cv2.CAP_PROP_POS_FRAMES, indice)
    ok, quadro = cap.read()
    if not ok:
        raise ValueError(f"Não consegui ler o quadro {indice}.")
    return quadro


def _referencia(cap, indice, orb):
    quadro = _ler_quadro(cap, indice)
    cinza = cv2.cvtColor(quadro, cv2.COLOR_BGR2GRAY)
    kp, des = orb.detectAndCompute(cinza, None)
    return quadro, kp, des


def analisar(entrada, referencia=None, passo=30):
    """Percorre o vídeo e mede, a cada `passo` quadros, o quanto ele se afasta da referência."""
    cap = _abrir(entrada)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    largura, altura = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    referencia = total // 2 if referencia is None else referencia
    orb = _criar_orb()
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    _, kp_ref, des_ref = _referencia(cap, referencia, orb)
    registros = []
    for i in range(0, total, passo):
        quadro = _ler_quadro(cap, i)
        cinza = cv2.cvtColor(quadro, cv2.COLOR_BGR2GRAY)
        H, inliers = estimar_homografia(kp_ref, des_ref, cinza, orb, matcher)
        desc = descrever_homografia(H, largura, altura) if H is not None else None
        registros.append({"quadro": i, "inliers": inliers, "desc": desc, "valido": quadro_valido(desc)})
    cap.release()
    return {"total": total, "largura": largura, "altura": altura,
            "fps": None, "referencia": referencia, "registros": registros}


def estabilizar(entrada, saida, referencia, inicio, fim, caminho_referencia=None):
    """
    Grava em `saida` os quadros inicio..fim deformados para a geometria do
    quadro `referencia`. Quando a estimativa falha num quadro, repete a última
    homografia boa (e conta). Retorna um dict com estatísticas.
    """
    cap = _abrir(entrada)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if not (0 <= inicio <= fim < total):
        raise ValueError(f"Intervalo inválido: 0 <= inicio ({inicio}) <= fim ({fim}) < total ({total}).")
    orb = _criar_orb()
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    quadro_ref, kp_ref, des_ref = _referencia(cap, referencia, orb)
    altura, largura = quadro_ref.shape[:2]
    if caminho_referencia:
        cv2.imwrite(caminho_referencia, quadro_ref)

    escritor = cv2.VideoWriter(saida, cv2.VideoWriter_fourcc(*"mp4v"), fps, (largura, altura))
    if not escritor.isOpened():
        raise ValueError(f"Não consegui criar o vídeo de saída: {saida}")

    cap.set(cv2.CAP_PROP_POS_FRAMES, inicio)
    ultima_H, repetidos, descartados_escala, escritos = np.eye(3), 0, 0, 0
    for i in range(inicio, fim + 1):
        ok, quadro = cap.read()
        if not ok:
            break
        cinza = cv2.cvtColor(quadro, cv2.COLOR_BGR2GRAY)
        H, _ = estimar_homografia(kp_ref, des_ref, cinza, orb, matcher)
        if H is not None and not quadro_valido(descrever_homografia(H, largura, altura)):
            descartados_escala += 1
        if H is None:
            H = ultima_H
            repetidos += 1
        else:
            ultima_H = H
        escritor.write(cv2.warpPerspective(quadro, H, (largura, altura)))
        escritos += 1
    escritor.release()
    cap.release()
    return {"escritos": escritos, "repetidos": repetidos, "fora_da_escala": descartados_escala,
            "fps": fps, "largura": largura, "altura": altura}


def _imprimir_analise(res):
    print(f"Vídeo: {res['total']} quadros, {res['largura']}x{res['altura']}; referência = quadro {res['referencia']}")
    print(f"{'quadro':>7} {'inliers':>8} {'dx(px)':>8} {'dy(px)':>8} {'escala':>7} {'rot(°)':>7}  válido")
    for r in res["registros"]:
        d = r["desc"]
        if d is None:
            print(f"{r['quadro']:>7} {r['inliers']:>8} {'-':>8} {'-':>8} {'-':>7} {'-':>7}  não")
        else:
            print(f"{r['quadro']:>7} {r['inliers']:>8} {d['dx']:>8.1f} {d['dy']:>8.1f} "
                  f"{d['escala']:>7.3f} {d['rotacao']:>7.2f}  {'sim' if r['valido'] else 'NÃO'}")
    trechos = segmentos_estaveis(res["registros"])
    print("\nTrechos estáveis em relação a essa referência (zoom/rotação ~ constantes):")
    if not trechos:
        print("  nenhum; tente outra referência (--referencia).")
    for a, b in trechos:
        print(f"  quadros {a} a {b}")


def main(argv=None):
    p = argparse.ArgumentParser(description="Estabiliza vídeo gravado na mão em relação a um quadro de referência.")
    p.add_argument("--entrada", required=True)
    p.add_argument("--saida")
    p.add_argument("--analisar", action="store_true", help="Só mede o movimento e sugere trechos")
    p.add_argument("--referencia", type=int, help="Quadro de referência (padrão: o do meio)")
    p.add_argument("--inicio", type=int, default=0)
    p.add_argument("--fim", type=int)
    p.add_argument("--passo", type=int, default=30, help="Intervalo de amostragem da análise (quadros)")
    args = p.parse_args(argv)

    try:
        if args.analisar:
            _imprimir_analise(analisar(args.entrada, args.referencia, args.passo))
            return 0
        if not args.saida or args.referencia is None or args.fim is None:
            print("Para estabilizar informe --saida, --referencia e --fim (use --analisar antes).")
            return 2
        ref_jpg = args.saida.rsplit(".", 1)[0] + "_referencia.jpg"
        est = estabilizar(args.entrada, args.saida, args.referencia, args.inicio, args.fim, ref_jpg)
    except ValueError as e:
        print(f"ERRO: {e}")
        return 1

    print(f"Gravado {args.saida}: {est['escritos']} quadros a {est['fps']:.2f} fps ({est['largura']}x{est['altura']}).")
    print(f"Quadro de referência para calibrar: {ref_jpg}")
    if est["repetidos"]:
        print(f"AVISO: {est['repetidos']} quadros sem alinhamento confiável repetiram a última correção.")
    if est["fora_da_escala"]:
        print(f"AVISO: {est['fora_da_escala']} quadros com zoom/rotação diferentes da referência; "
              "reduza o trecho ou use outra referência.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
