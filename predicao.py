"""
Predição de curto prazo da posição dos veículos e de aproximações perigosas.

Modelo (deliberadamente simples e explicável): cada veículo mantém a velocidade
vetorial estimada nos últimos instantes (movimento uniforme). Com isso:

  - posição prevista em t+h:      p(t+h) = p(t) + v * h
  - menor distância prevista entre dois veículos no intervalo [0, h], e em que
    instante ela ocorre (mínimo de |r + u t| para r = posição relativa e u =
    velocidade relativa).

Quando a menor distância prevista cai abaixo do limiar de proximidade e a
distância ATUAL ainda está acima dele, gera-se o evento "proximidade_prevista"
(antecipa o que "proximidade_perigosa" só registra quando já aconteceu).

A qualidade da predição é medida pelo AvaliadorPredicao: cada previsão de
posição é comparada com a posição real h segundos depois. Esse erro (em metros)
não depende de gabarito e é o resultado numérico da predição.

Funciona só com posições em metros (calibração por homografia ou por escala).
Sem dependências pesadas; testável isoladamente.
"""

import math
from collections import deque


def _segundos(ts, ref):
    delta = ts - ref
    return delta.total_seconds() if hasattr(delta, "total_seconds") else float(delta)


def posicao_atual_m(historico, escala):
    """Última posição do histórico em metros, ou None."""
    if escala is None or not historico:
        return None
    p = list(historico)[-1]
    return p["x"] * escala, p["y"] * escala


def estimar_velocidade_vetorial(historico, escala, janela=15, min_pontos=8, min_duracao_s=0.25):
    """
    Velocidade vetorial (vx, vy) em m/s por regressão linear das últimas
    `janela` posições (suaviza o tremor da caixa de detecção). Retorna None se
    não há calibração, pontos ou duração suficientes.
    """
    if escala is None:
        return None
    pts = list(historico)[-janela:]
    if len(pts) < min_pontos:
        return None
    t0 = pts[0]["timestamp"]
    ts = [_segundos(p["timestamp"], t0) for p in pts]
    if ts[-1] - ts[0] < min_duracao_s:
        return None
    tm = sum(ts) / len(ts)
    sxx = sum((t - tm) ** 2 for t in ts)
    if sxx <= 0:
        return None
    xs = [p["x"] * escala for p in pts]
    ys = [p["y"] * escala for p in pts]
    xm, ym = sum(xs) / len(xs), sum(ys) / len(ys)
    vx = sum((t - tm) * (x - xm) for t, x in zip(ts, xs)) / sxx
    vy = sum((t - tm) * (y - ym) for t, y in zip(ts, ys)) / sxx
    return vx, vy


def posicao_prevista(pos, vel, horizonte_s):
    return pos[0] + vel[0] * horizonte_s, pos[1] + vel[1] * horizonte_s


def menor_distancia_prevista(pos_a, vel_a, pos_b, vel_b, horizonte_s):
    """
    Menor distância (m) entre A e B em t no intervalo [0, horizonte_s] e o
    instante t* (s) em que ocorre, com movimento uniforme.
    """
    rx, ry = pos_b[0] - pos_a[0], pos_b[1] - pos_a[1]
    ux, uy = vel_b[0] - vel_a[0], vel_b[1] - vel_a[1]
    uu = ux * ux + uy * uy
    if uu < 1e-12:
        return math.hypot(rx, ry), 0.0
    t = -(rx * ux + ry * uy) / uu
    t = max(0.0, min(horizonte_s, t))
    return math.hypot(rx + ux * t, ry + uy * t), t


class AvaliadorPredicao:
    """
    Mede o erro da previsão de posição: a cada quadro registra a posição que
    cada alvo teria em t+h (movimento uniforme) e, quando o tempo chega, compara
    com a posição real. Também calcula o erro de uma "não-previsão" (supor que o
    veículo fica parado), que é a linha de base de comparação.
    """

    def __init__(self, horizonte_s, tolerancia_s=0.15, vel_minima_m_s=2.0):
        self.horizonte_s = horizonte_s
        self.tolerancia_s = tolerancia_s
        self.vel_minima_m_s = vel_minima_m_s
        self._pendentes = deque()   # (ts_alvo, tid, ts0, x0, y0, vx, vy)
        self.amostras = []          # dicts {erro_prev, erro_parado, vel, dist_prev}

    def registrar(self, ts, tid, pos, vel, tipo=None):
        """Guarda a previsão feita no instante ts para ts + horizonte."""
        ts_alvo = ts + _como_delta(self.horizonte_s, ts)
        self._pendentes.append((ts_alvo, tid, ts, pos[0], pos[1], vel[0], vel[1], tipo))

    def conferir(self, ts, posicoes):
        """posicoes: {track_id: (x_m, y_m)} no instante ts (quadro atual)."""
        while self._pendentes and _segundos(ts, self._pendentes[0][0]) >= 0:
            ts_alvo, tid, ts0, x0, y0, vx, vy, tipo = self._pendentes.popleft()
            atraso = _segundos(ts, ts_alvo)
            real = posicoes.get(tid)
            if real is None or atraso > self.tolerancia_s:
                continue  # veículo sumiu (oclusão/troca de ID) ou quadro muito atrasado
            dt = _segundos(ts, ts0)  # tempo decorrido exato até este quadro
            px, py = x0 + vx * dt, y0 + vy * dt
            self.amostras.append({
                "erro_prev": math.hypot(real[0] - px, real[1] - py),
                "erro_parado": math.hypot(real[0] - x0, real[1] - y0),
                "vel": math.hypot(vx, vy),
                "dist_prev": math.hypot(vx, vy) * dt,
                "tipo": tipo,
            })

    def resumo(self):
        """Estatísticas do erro (m). 'em_movimento' filtra vel >= vel_minima_m_s."""
        def estat(am):
            if not am:
                return None
            e = sorted(a["erro_prev"] for a in am)
            p = sorted(a["erro_parado"] for a in am)
            def pct(v, q):
                return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]
            return {
                "n": len(am),
                "erro_medio_m": sum(e) / len(e),
                "erro_mediano_m": pct(e, 0.5),
                "erro_p90_m": pct(e, 0.9),
                "erro_parado_medio_m": sum(p) / len(p),
            }
        mov = [a for a in self.amostras if a["vel"] >= self.vel_minima_m_s]
        motos = [a for a in self.amostras if a.get("tipo") == "motorcycle"]
        return {"horizonte_s": self.horizonte_s, "todos": estat(self.amostras),
                "em_movimento": estat(mov), "motos": estat(motos)}

    def texto_resumo(self):
        r = self.resumo()
        if not r["todos"]:
            return "Predição: nenhuma amostra avaliada (sem calibração, ou veículos rastreados por pouco tempo)."
        linhas = [f"Predição de posição a {self.horizonte_s:g} s — erro entre posição prevista e posição real:"]
        for nome, chave in (("todos os veículos", "todos"),
                            (f"veículos em movimento (>= {self.vel_minima_m_s:g} m/s)", "em_movimento"),
                            ("motos", "motos")):
            e = r[chave]
            if e:
                linhas.append(
                    f"  {nome}: n={e['n']}, erro médio {e['erro_medio_m']:.2f} m, mediana "
                    f"{e['erro_mediano_m']:.2f} m, p90 {e['erro_p90_m']:.2f} m "
                    f"(sem predição, supondo parado: {e['erro_parado_medio_m']:.2f} m)"
                )
        return "\n".join(linhas)


def _como_delta(segundos, ref):
    """Soma de `segundos` a um timestamp datetime ou numérico."""
    if hasattr(ref, "year"):
        from datetime import timedelta
        return timedelta(seconds=segundos)
    return segundos
