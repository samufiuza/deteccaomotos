"""
Calibração por homografia a partir de N pontos de referência no chão (N >= 4).

Quando não há um retângulo medível na cena, usa-se vários pontos do chão que
aparecem tanto no vídeo quanto no Google Earth Pro (pontas de traços de faixa,
cantos de faixa de pedestres, quinas de meio-fio...). Para cada ponto:

  - pixel (px, py) no quadro da câmera;
  - posição real: latitude/longitude lidas no Google Earth Pro
    (ou, se preferir, x_m / y_m já em metros num sistema planar qualquer).

Com 5 ou mais pontos a homografia é ajustada por mínimos quadrados e o script
informa o erro de cada ponto (em metros), inclusive "deixando um de fora"
(leave-one-out), que é a medida honesta de quão bem a calibração generaliza.

O arquivo JSON gerado tem o mesmo formato da ferramenta_calibracao.py e é
usado do mesmo jeito: main.py --calib-arquivo <saida>.

Uso:
    # 1) marcar os pontos no quadro (gera o CSV com lat/lon em branco)
    python calibrar_por_pontos.py --marcar --imagem balneario_frame.jpg --pontos pontos.csv

    # 2) preencher lat/lon no CSV (Google Earth Pro, graus decimais) e calibrar
    python calibrar_por_pontos.py --pontos pontos.csv --imagem balneario_frame.jpg \
        --saida calib_balneario.json --validacao 482,423,590,482,4.00 \
        --conferencia conferencia.jpg
"""

import argparse
import csv
import math
import sys

import numpy as np

from calibration import aplicar_homografia, salvar_calibracao

RAIO_TERRA_M = 6371008.8

# Limites de referência (orientativos) para o erro médio quadrático em metros.
LIMITE_BOM_M = 0.5
LIMITE_ACEITAVEL_M = 1.0


# ---------------------------------------------------------------------------
# Geometria
# ---------------------------------------------------------------------------

def latlon_para_metros(pontos_latlon):
    """
    Converte [(lat, lon), ...] em graus para [(x, y), ...] em metros, num plano
    local centrado na média dos pontos (x = leste, y = norte).

    Para áreas de dezenas de metros a aproximação equiretangular tem erro
    desprezível (muito abaixo do erro de leitura no Google Earth).
    """
    pts = np.asarray(pontos_latlon, dtype=float)
    lat0 = float(pts[:, 0].mean())
    lon0 = float(pts[:, 1].mean())
    cos_lat0 = math.cos(math.radians(lat0))
    saida = []
    for lat, lon in pts:
        x = RAIO_TERRA_M * cos_lat0 * math.radians(lon - lon0)
        y = RAIO_TERRA_M * math.radians(lat - lat0)
        saida.append((x, y))
    return saida


def _matriz_normalizacao(pontos):
    pts = np.asarray(pontos, dtype=float)
    centro = pts.mean(axis=0)
    dist_media = float(np.mean(np.linalg.norm(pts - centro, axis=1)))
    if dist_media < 1e-12:
        raise ValueError("Pontos de calibração repetidos (todos no mesmo lugar).")
    s = math.sqrt(2.0) / dist_media
    return np.array([[s, 0.0, -s * centro[0]],
                     [0.0, s, -s * centro[1]],
                     [0.0, 0.0, 1.0]])


def _matriz_normalizacao_mundo(pontos):
    """
    Normalização das coordenadas reais quando alguns pontos têm só X ou só Y
    (None na coordenada desconhecida). Usa apenas os valores conhecidos.
    """
    xs = [p[0] for p in pontos if p[0] is not None]
    ys = [p[1] for p in pontos if p[1] is not None]
    if not xs or not ys:
        raise ValueError("É preciso haver pontos com X conhecido e pontos com Y conhecido.")
    cx, cy = float(np.mean(xs)), float(np.mean(ys))
    d = math.sqrt(float(np.mean([(x - cx) ** 2 for x in xs])) + float(np.mean([(y - cy) ** 2 for y in ys])))
    if d < 1e-12:
        raise ValueError("Pontos de calibração repetidos (todos no mesmo lugar).")
    s = math.sqrt(2.0) / d
    return np.array([[s, 0.0, -s * cx],
                     [0.0, s, -s * cy],
                     [0.0, 0.0, 1.0]])


def homografia_minimos_quadrados(pontos_imagem, pontos_mundo):
    """
    Homografia H (3x3) que leva pixels -> metros, ajustada por DLT normalizado
    (Hartley) com N >= 4 pontos. Com 4 pontos completos coincide com a solução
    exata de calibration.calcular_homografia.

    pontos_mundo aceita restrições PARCIAIS: um ponto (X, None) só informa a
    coordenada X (por exemplo, um ponto sobre uma linha de borda da pista, cuja
    distância lateral ao eixo é conhecida mas a posição ao longo da via não);
    (None, Y) só informa Y. Cada coordenada conhecida vale uma equação, e são
    necessárias pelo menos 8 no total.

    Levanta ValueError se houver menos de 4 pontos, poucas equações ou se os
    pontos forem degenerados (por exemplo, todos colineares).
    """
    if len(pontos_imagem) != len(pontos_mundo):
        raise ValueError("Número de pontos na imagem e no mundo diferente.")
    n = len(pontos_imagem)
    if n < 4:
        raise ValueError(f"São necessários pelo menos 4 pontos (recebidos: {n}).")
    if any(X is None and Y is None for X, Y in pontos_mundo):
        raise ValueError("Há ponto sem nenhuma coordenada real conhecida.")
    equacoes = sum((X is not None) + (Y is not None) for X, Y in pontos_mundo)
    if equacoes < 8:
        raise ValueError(f"Poucas restrições: {equacoes} coordenadas conhecidas (mínimo 8).")

    Ti = _matriz_normalizacao(pontos_imagem)
    Tw = _matriz_normalizacao_mundo(pontos_mundo)
    cx, cy, s = -Tw[0, 2] / Tw[0, 0], -Tw[1, 2] / Tw[1, 1], Tw[0, 0]

    linhas = []
    for (x, y), (X, Y) in zip(pontos_imagem, pontos_mundo):
        u, v, _ = Ti @ np.array([x, y, 1.0])
        if X is not None:
            a = s * (X - cx)
            linhas.append([-u, -v, -1.0, 0.0, 0.0, 0.0, a * u, a * v, a])
        if Y is not None:
            b = s * (Y - cy)
            linhas.append([0.0, 0.0, 0.0, -u, -v, -1.0, b * u, b * v, b])
    A = np.array(linhas, dtype=float)
    if len(A) < 9:
        A = np.vstack([A, np.zeros((9 - len(A), 9))])  # garante 9 valores singulares

    _, S, Vt = np.linalg.svd(A)
    if S[-2] < 1e-7 * S[0]:
        raise ValueError(
            "Pontos de calibração degenerados (colineares ou quase). "
            "Inclua pontos fora de uma mesma linha."
        )
    Hn = Vt[-1].reshape(3, 3)
    H = np.linalg.inv(Tw) @ Hn @ Ti
    if abs(H[2, 2]) < 1e-12:
        raise ValueError("Homografia degenerada (H[2,2] ~ 0).")
    H = H / H[2, 2]
    if not np.all(np.isfinite(H)) or abs(np.linalg.det(H)) < 1e-18:
        raise ValueError("Homografia degenerada (matriz não inversível).")
    return H


def erros_reprojecao(H, pontos_imagem, pontos_mundo):
    """Erro (m) de cada ponto: distância entre a projeção de H e a posição real."""
    erros = []
    for (x, y), (X, Y) in zip(pontos_imagem, pontos_mundo):
        p = aplicar_homografia(H, x, y)
        if p is None:
            erros.append(math.inf)
            continue
        dx = 0.0 if X is None else p[0] - X
        dy = 0.0 if Y is None else p[1] - Y
        erros.append(math.hypot(dx, dy))  # em ponto parcial, só a coordenada conhecida conta
    return erros


def completar_mundo(H, pontos_imagem, pontos_mundo):
    """Preenche a coordenada desconhecida de pontos parciais com o valor projetado por H."""
    completos = []
    for (x, y), (X, Y) in zip(pontos_imagem, pontos_mundo):
        if X is not None and Y is not None:
            completos.append((X, Y))
            continue
        p = aplicar_homografia(H, x, y)
        completos.append((p[0] if X is None else X, p[1] if Y is None else Y))
    return completos


def pontos_transversais_horizontais(pontos_imagem, pontos_mundo, min_pontos_linha=2, min_extensao_px=20.0):
    """
    Gera pontos extras sob a hipótese de que as linhas TRANSVERSAIS à via (as de
    mesmo Y) aparecem como linhas horizontais na imagem. Isso vale com boa
    aproximação quando a câmera olha ao longo da via e está sem inclinação
    lateral (roll), como numa passarela sobre uma rodovia.

    Entrada: pontos completos (X, Y) no eixo da via (ex.: pontas de traço) e pontos
    parciais (X, None) sobre linhas de borda (X = distância lateral ao eixo).
    Para cada ponto completo e cada linha de borda, o pixel onde a linha de borda
    cruza a mesma linha da imagem (mesmo v) recebe as coordenadas (X_borda, Y).
    Retorna (pixels, mundo) dos pontos novos.
    """
    linhas = {}
    for (u, v), (X, Y) in zip(pontos_imagem, pontos_mundo):
        if X is not None and Y is None:
            linhas.setdefault(round(float(X), 6), []).append((u, v))
    ajustes = {}
    for X, pts in linhas.items():
        if len(pts) < min_pontos_linha:
            continue
        us, vs = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
        if float(vs.max() - vs.min()) < min_extensao_px:
            continue
        a, b = np.polyfit(vs, us, 1)  # u = a*v + b (linhas da via são quase verticais na imagem)
        ajustes[X] = (float(a), float(b))
    novos_img, novos_mundo = [], []
    for (u, v), (X, Y) in zip(pontos_imagem, pontos_mundo):
        if X is None or Y is None:
            continue
        for Xl, (a, b) in ajustes.items():
            if abs(Xl - X) < 1e-6:
                continue
            novos_img.append((a * v + b, v))
            novos_mundo.append((Xl, float(Y)))
    return novos_img, novos_mundo


def ajustar_homografia(pontos_imagem, pontos_mundo, transversais_horizontais=False):
    """Ajuste da homografia, opcionalmente acrescentando os pontos transversais horizontais."""
    img, mundo = list(pontos_imagem), list(pontos_mundo)
    if transversais_horizontais:
        extra_img, extra_mundo = pontos_transversais_horizontais(img, mundo)
        img, mundo = img + extra_img, mundo + extra_mundo
    try:
        return homografia_minimos_quadrados(img, mundo)
    except ValueError as e:
        if any((X is None) != (Y is None) for X, Y in pontos_mundo) and not transversais_horizontais:
            raise ValueError(
                f"{e} Com pontos parciais falta informação da direção transversal da via: "
                "use --transversais-horizontais ou informe pontos de borda com Y conhecido."
            ) from e
        raise


def erros_leave_one_out(pontos_imagem, pontos_mundo, transversais_horizontais=False):
    """
    Para cada ponto: ajusta a homografia SEM ele e mede o erro (m) nele.
    Retorna None se houver menos de 5 pontos (sobraria menos de 4 para ajustar).
    Um ponto cuja homografia não pôde ser ajustada sem ele recebe inf.
    """
    n = len(pontos_imagem)
    if n < 5:
        return None
    erros = []
    for i in range(n):
        img = [p for j, p in enumerate(pontos_imagem) if j != i]
        mun = [p for j, p in enumerate(pontos_mundo) if j != i]
        try:
            H = ajustar_homografia(img, mun, transversais_horizontais)
        except ValueError:
            erros.append(math.inf)
            continue
        erros.append(erros_reprojecao(H, [pontos_imagem[i]], [pontos_mundo[i]])[0])
    return erros


def ponto_suspeito(pontos_imagem, pontos_mundo, transversais_horizontais=False):
    """
    Procura o ponto que mais prejudica a calibração: o que, ao ser removido,
    mais reduz o erro RMS dos demais. Retorna (indice, rms_com, rms_sem) ou
    None se não houver suspeito claro (precisa de 6+ pontos e queda de pelo
    menos 50% no RMS).
    """
    n = len(pontos_imagem)
    if n < 6:
        return None

    def rms_de(img, mun):
        H = ajustar_homografia(img, mun, transversais_horizontais)
        e = erros_reprojecao(H, img, mun)
        return math.sqrt(sum(x * x for x in e) / len(e))

    try:
        rms_com = rms_de(pontos_imagem, pontos_mundo)
    except ValueError:
        return None
    melhor = None
    for i in range(n):
        img = [p for j, p in enumerate(pontos_imagem) if j != i]
        mun = [p for j, p in enumerate(pontos_mundo) if j != i]
        try:
            rms_sem = rms_de(img, mun)
        except ValueError:
            continue
        if melhor is None or rms_sem < melhor[2]:
            melhor = (i, rms_com, rms_sem)
    if melhor is None or melhor[2] > 0.5 * rms_com:
        return None
    return melhor


def validar_distancia(H, ponto_a, ponto_b, distancia_real_m):
    """
    Distância prevista pela homografia entre dois pixels do chão, comparada à
    medida real. Retorna (medida_m, erro_percentual) ou (None, None).
    """
    a = aplicar_homografia(H, *ponto_a)
    b = aplicar_homografia(H, *ponto_b)
    if a is None or b is None or distancia_real_m <= 0:
        return None, None
    medida = math.dist(a, b)
    return medida, (medida - distancia_real_m) / distancia_real_m * 100.0


def _casco_convexo(pontos):
    pts = sorted(set(map(tuple, pontos)))
    if len(pts) <= 2:
        return pts

    def cruz(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    inferior = []
    for p in pts:
        while len(inferior) >= 2 and cruz(inferior[-2], inferior[-1], p) <= 0:
            inferior.pop()
        inferior.append(p)
    superior = []
    for p in reversed(pts):
        while len(superior) >= 2 and cruz(superior[-2], superior[-1], p) <= 0:
            superior.pop()
        superior.append(p)
    return inferior[:-1] + superior[:-1]


def cobertura_da_imagem(pontos_imagem, resolucao):
    """Fração da área da imagem coberta pelo casco convexo dos pontos (0 a 1)."""
    casco = _casco_convexo(pontos_imagem)
    if len(casco) < 3:
        return 0.0
    area = 0.0
    for (x1, y1), (x2, y2) in zip(casco, casco[1:] + casco[:1]):
        area += x1 * y2 - x2 * y1
    area = abs(area) / 2.0
    return area / float(resolucao[0] * resolucao[1])


# ---------------------------------------------------------------------------
# Arquivo de pontos (CSV)
# ---------------------------------------------------------------------------

def _numero(texto):
    return float(str(texto).strip().replace(",", "."))


def escrever_modelo_csv(pontos_px, caminho):
    """Gera o CSV de pontos com pixel preenchido e lat/lon em branco (separador ';')."""
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        f.write("nome;px;py;lat;lon\n")
        for i, (x, y) in enumerate(pontos_px, start=1):
            f.write(f"P{i};{x:.0f};{y:.0f};;\n")


def carregar_pontos(caminho):
    """
    Lê o CSV de pontos. Separador ';' ou ','. Com ';' aceita decimal com
    vírgula (formato do Google Earth em português).

    Colunas: nome, px, py e (lat, lon) OU (x_m, y_m).
    Retorna dict com nomes, pontos_imagem, pontos_mundo_m, fonte.
    """
    with open(caminho, "r", encoding="utf-8-sig") as f:
        texto = f.read()
    linhas = [l for l in texto.splitlines() if l.strip() and not l.strip().startswith("#")]
    if len(linhas) < 2:
        raise ValueError(f"{caminho}: arquivo sem pontos.")
    delim = ";" if ";" in linhas[0] else ","
    leitor = csv.DictReader(linhas, delimiter=delim)
    campos = [c.strip().lower() for c in (leitor.fieldnames or [])]
    leitor.fieldnames = campos
    for obrigatorio in ("nome", "px", "py"):
        if obrigatorio not in campos:
            raise ValueError(f"{caminho}: falta a coluna '{obrigatorio}'.")
    usa_latlon = "lat" in campos and "lon" in campos
    usa_metros = "x_m" in campos and "y_m" in campos
    if not (usa_latlon or usa_metros):
        raise ValueError(f"{caminho}: use as colunas lat/lon ou x_m/y_m.")

    nomes, img, mundo, incompletos = [], [], [], []
    for linha in leitor:
        nome = (linha.get("nome") or "").strip()
        a, b = (("lat", "lon") if usa_latlon else ("x_m", "y_m"))
        va, vb = (linha.get(a) or "").strip(), (linha.get(b) or "").strip()
        # Em metros, uma coordenada em branco vale como restrição parcial (só X ou só Y).
        if (not va and not vb) or (usa_latlon and (not va or not vb)):
            incompletos.append(nome)
            continue
        try:
            nomes.append(nome)
            img.append((_numero(linha["px"]), _numero(linha["py"])))
            mundo.append((_numero(va) if va else None, _numero(vb) if vb else None))
        except ValueError as e:
            raise ValueError(f"{caminho}: valor inválido no ponto '{nome}'.") from e
    if incompletos:
        raise ValueError(
            f"{caminho}: preencha {a}/{b} dos pontos: {', '.join(incompletos)} "
            "(ou apague essas linhas)."
        )
    if usa_latlon:
        mundo = latlon_para_metros(mundo)
    return {
        "nomes": nomes,
        "pontos_imagem": img,
        "pontos_mundo_m": mundo,
        "fonte": "latlon" if usa_latlon else "metros",
    }


# ---------------------------------------------------------------------------
# Relatório e imagem de conferência
# ---------------------------------------------------------------------------

def classificar_rms(rms_m):
    if rms_m <= LIMITE_BOM_M:
        return "BOA"
    if rms_m <= LIMITE_ACEITAVEL_M:
        return "ACEITÁVEL"
    return "RUIM"


def desenhar_conferencia(imagem, H, nomes, pontos_imagem, pontos_mundo, validacoes, caminho):
    """
    Salva uma imagem com: pontos clicados (verde), onde a homografia os coloca
    (vermelho) e os segmentos de validação com medida prevista x real.
    """
    import cv2

    quadro = imagem.copy()
    H_inv = np.linalg.inv(H)
    for nome, (x, y), (X, Y) in zip(nomes, pontos_imagem, pontos_mundo):
        cv2.circle(quadro, (int(round(x)), int(round(y))), 6, (0, 255, 0), 2)
        v = H_inv @ np.array([X, Y, 1.0])
        if abs(v[2]) > 1e-12:
            px, py = v[0] / v[2], v[1] / v[2]
            cv2.circle(quadro, (int(round(px)), int(round(py))), 3, (0, 0, 255), -1)
            cv2.line(quadro, (int(round(x)), int(round(y))), (int(round(px)), int(round(py))), (0, 0, 255), 1)
        cv2.putText(quadro, nome, (int(x) + 8, int(y) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    for (x1, y1, x2, y2, real, medida, erro) in validacoes:
        cv2.line(quadro, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 255), 2)
        rotulo = "validacao: real {:.2f} m".format(real)
        if medida is not None:
            rotulo += " | previsto {:.2f} m ({:+.0f}%)".format(medida, erro)
        cv2.putText(quadro, rotulo, (int(min(x1, x2)), int(min(y1, y2)) - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)
    cv2.imwrite(caminho, quadro)


def _parse_validacao(texto):
    partes = [p.strip() for p in texto.replace(";", ",").split(",")]
    if len(partes) != 5:
        raise ValueError("--validacao espera x1,y1,x2,y2,distancia_m (ex.: 482,423,590,482,4.00)")
    x1, y1, x2, y2, d = (_numero(p) for p in partes)
    if d <= 0:
        raise ValueError("A distância de validação deve ser positiva.")
    return x1, y1, x2, y2, d


def _parse_resolucao(texto):
    try:
        w, h = texto.lower().split("x")
        return int(w), int(h)
    except ValueError as e:
        raise ValueError("--resolucao deve ser LARGURAxALTURA (ex.: 1280x720)") from e


# ---------------------------------------------------------------------------
# Marcação interativa dos pontos
# ---------------------------------------------------------------------------

def marcar_pontos(imagem_path, csv_path):
    """Abre a imagem; clique esquerdo marca, 'u' desfaz, 'q'/Esc salva o CSV."""
    import cv2

    base = cv2.imread(imagem_path)
    if base is None:
        raise ValueError(f"Não consegui abrir a imagem: {imagem_path}")
    pontos = []
    nome_janela = "Marcar pontos (clique=marca, u=desfaz, q=salvar)"

    def redesenhar():
        quadro = base.copy()
        for i, (x, y) in enumerate(pontos, start=1):
            cv2.circle(quadro, (x, y), 5, (0, 255, 0), 2)
            cv2.putText(quadro, f"P{i}", (x + 8, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imshow(nome_janela, quadro)

    def clique(evento, x, y, flags, param):
        if evento == cv2.EVENT_LBUTTONDOWN:
            pontos.append((x, y))
            redesenhar()

    cv2.namedWindow(nome_janela)
    cv2.setMouseCallback(nome_janela, clique)
    redesenhar()
    while True:
        tecla = cv2.waitKey(50) & 0xFF
        if tecla in (ord("q"), 27):
            break
        if tecla == ord("u") and pontos:
            pontos.pop()
            redesenhar()
        if cv2.getWindowProperty(nome_janela, cv2.WND_PROP_VISIBLE) < 1:
            break
    cv2.destroyAllWindows()
    if not pontos:
        print("Nenhum ponto marcado; nada foi salvo.")
        return []
    escrever_modelo_csv(pontos, csv_path)
    print(f"{len(pontos)} pontos salvos em {csv_path}. Preencha as colunas lat e lon.")
    return pontos


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description="Calibração por homografia com N pontos do chão.")
    p.add_argument("--pontos", required=True, help="CSV de pontos (nome;px;py;lat;lon)")
    p.add_argument("--imagem", help="Quadro usado para marcar os pontos (define a resolução)")
    p.add_argument("--resolucao", help="LARGURAxALTURA, se não houver --imagem (ex.: 1280x720)")
    p.add_argument("--saida", default="calibracao_resultado.json")
    p.add_argument("--validacao", action="append", default=[],
                   help="x1,y1,x2,y2,distancia_m (repetível). Use medidas que NÃO entraram na calibração.")
    p.add_argument("--conferencia", help="Salva uma imagem de conferência (requer --imagem)")
    p.add_argument("--descricao", default="")
    p.add_argument("--transversais-horizontais", action="store_true",
                   help="Para vias retas vistas de frente (ex.: passarela sobre rodovia): supõe que as "
                        "linhas transversais à via são horizontais na imagem e as usa com os pontos parciais")
    p.add_argument("--marcar", action="store_true", help="Modo interativo: marca os pontos e gera o CSV")
    args = p.parse_args(argv)

    if args.marcar:
        if not args.imagem:
            print("--marcar exige --imagem.")
            return 2
        marcar_pontos(args.imagem, args.pontos)
        return 0

    imagem = None
    if args.imagem:
        import cv2
        imagem = cv2.imread(args.imagem)
        if imagem is None:
            print(f"Não consegui abrir a imagem: {args.imagem}")
            return 2
        resolucao = (imagem.shape[1], imagem.shape[0])
    elif args.resolucao:
        resolucao = _parse_resolucao(args.resolucao)
    else:
        print("Informe --imagem ou --resolucao.")
        return 2

    try:
        dados = carregar_pontos(args.pontos)
        validacoes_in = [_parse_validacao(v) for v in args.validacao]
        H = ajustar_homografia(dados["pontos_imagem"], dados["pontos_mundo_m"], args.transversais_horizontais)
    except ValueError as e:
        print(f"ERRO: {e}")
        return 1

    nomes, img, mundo = dados["nomes"], dados["pontos_imagem"], dados["pontos_mundo_m"]
    erros = erros_reprojecao(H, img, mundo)
    rms = math.sqrt(sum(e * e for e in erros) / len(erros))
    loo = erros_leave_one_out(img, mundo, args.transversais_horizontais)

    print(f"\nPontos usados: {len(nomes)} (fonte das coordenadas: {dados['fonte']})")
    print(f"{'ponto':<10}{'erro (m)':>10}{'sem ele (m)':>14}")
    for i, nome in enumerate(nomes):
        sem = f"{loo[i]:.2f}" if loo is not None else "-"
        print(f"{nome:<10}{erros[i]:>10.2f}{sem:>14}")
    print(f"\nErro médio quadrático (RMS): {rms:.2f} m  -> {classificar_rms(rms)}")
    if loo is not None:
        finitos = [e for e in loo if math.isfinite(e)]
        if finitos:
            print(f"Erro leave-one-out médio: {sum(finitos) / len(finitos):.2f} m "
                  f"(máx {max(finitos):.2f} m)")
    else:
        print("Leave-one-out indisponível (use 5 ou mais pontos para estimar a generalização).")

    suspeito = ponto_suspeito(img, mundo, args.transversais_horizontais)
    if suspeito is not None:
        i, rms_com, rms_sem = suspeito
        print(f"Ponto suspeito: {nomes[i]} (sem ele o RMS cai de {rms_com:.2f} m para {rms_sem:.2f} m). "
              "Confira o pixel clicado e a coordenada dele.")

    cob = cobertura_da_imagem(img, resolucao)
    print(f"Cobertura da imagem pelos pontos: {cob * 100:.0f}%")
    if cob < 0.10:
        print("AVISO: pontos concentrados numa área pequena; a calibração tende a ser instável "
              "fora dela. Inclua pontos mais perto e mais longe da câmera.")
    if len(nomes) == 4:
        print("AVISO: com exatamente 4 pontos o ajuste é exato e não há como estimar o erro. "
              "Prefira 6 ou mais.")

    validacoes_out = []
    for (x1, y1, x2, y2, real) in validacoes_in:
        medida, erro = validar_distancia(H, (x1, y1), (x2, y2), real)
        validacoes_out.append((x1, y1, x2, y2, real, medida, erro))
        if medida is None:
            print(f"Validação ({x1:.0f},{y1:.0f})->({x2:.0f},{y2:.0f}): não foi possível calcular.")
        else:
            print(f"Validação ({x1:.0f},{y1:.0f})->({x2:.0f},{y2:.0f}): real {real:.2f} m | "
                  f"previsto {medida:.2f} m | erro {erro:+.1f}%")

    if args.transversais_horizontais:
        print("AVISO: hipótese ativa: linhas transversais à via horizontais na imagem. Valide com "
              "uma medida independente (ex.: largura da pista num ponto que não entrou no ajuste).")
    parciais = sum((X is None) != (Y is None) for X, Y in mundo)
    if parciais:
        print(f"Pontos com restrição parcial (só X ou só Y): {parciais}; "
              "o erro deles considera apenas a coordenada conhecida.")
    mundo = completar_mundo(H, img, mundo)
    descricao = args.descricao or f"{len(nomes)} pontos de referência (mínimos quadrados), RMS {rms:.2f} m"
    salvar_calibracao(args.saida, H, img, mundo, resolucao, descricao)
    print(f"\nCalibração salva em {args.saida}")

    if args.conferencia:
        if imagem is None:
            print("--conferencia exige --imagem; imagem de conferência não gerada.")
        else:
            desenhar_conferencia(imagem, H, nomes, img, mundo, validacoes_out, args.conferencia)
            print(f"Imagem de conferência: {args.conferencia}")

    if rms > LIMITE_ACEITAVEL_M:
        print("ATENÇÃO: erro alto. Revise pontos mal marcados antes de usar este arquivo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
