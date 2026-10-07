# Pipeline consolidado — Detecção + Tracking + Velocidade + Distância + Zona de Risco + Tendência + Score + Dashboard

Substitui `detectio_motos.py`, `detection.py` e `main.py` do projeto original.

## Estrutura

```
config.py            - configurações (modelo, classes, banco, limiares e pesos do score via env vars)
calibration.py        - calibração: fator pixel->metro (simples) e HOMOGRAFIA (plano do chão, recomendada)
detector.py           - detecção + tracking (YOLO + ByteTrack nativo do Ultralytics)
risk.py               - velocidade, distância, zona, tendência (mudança brusca/aproximação rápida), parado, score
state.py              - histórico de posições/distâncias, zonas, tendência e score por track_id (sem YOLO/banco)
fonte.py              - nome amigável da origem (--origem) e tempo de cada quadro (vídeo x ao vivo)
db.py                 - conexão e persistência no PostgreSQL (detecções + eventos + análise de risco)
main.py               - orquestração / ponto de entrada (processa vídeo/imagem, popula o banco)
dashboard_queries.py  - consultas ao banco para o dashboard (testável sem Streamlit/Postgres real)
dashboard.py          - interface Streamlit (só lê o que já está no banco)
zonas_exemplo.json    - exemplo de configuração de zonas de risco
```

## Instalação

```bash
pip install -r requirements.txt
```

## Configuração do banco

```bash
export DB_HOST=localhost
export DB_NAME=projeto_motos
export DB_USER=postgres
export DB_PASSWORD=sua_senha
```

A tabela `deteccoes` é criada automaticamente na primeira execução, caso não exista.

## Uso

```bash
# vídeo, sem calibração (velocidade não é calculada, distância fica em pixels)
python main.py --source vídeo_moto.mp4

# vídeo, com calibração por HOMOGRAFIA (recomendado — ver "Como calibrar" abaixo)
python main.py --source vídeo_moto.mp4 --calib-arquivo calibracao_resultado.json

# calibração simples (um fator único; só serve para câmera quase de cima)
python main.py --source vídeo_moto.mp4 \
    --calib-p1 "100,400" --calib-p2 "500,400" --calib-dist 8

# com nome amigável para o vídeo (vai para o banco e para o filtro do dashboard)
python main.py --source "C:/caminho/muito/longo/vídeo_moto.mp4" --origem "congestionamento_teste"

# parados contam como vizinho de quem se move (ver "Filtro do cálculo de distância")
python main.py --source vídeo_moto.mp4 --parados so_alvo --origem cong_so_alvo

# imagem
python main.py --source moto_teste.jpg

# webcam
python main.py --source 0

# com zonas de risco (ver zonas_exemplo.json — ajuste as coordenadas pro seu vídeo)
python main.py --source vídeo_moto.mp4 --zonas zonas_exemplo.json

# sem abrir janela (ex.: rodando em servidor)
python main.py --source vídeo_moto.mp4 --no-display
```

Para fechar a janela durante o processamento: tecla `q` ou o botão **X** da janela
(os dados processados até ali são salvos normalmente).

### Origem do vídeo (`--origem`)

Cada registro de `deteccoes`, `eventos` e `analise_risco` guarda `origem_video`.
Por padrão é só o **nome do arquivo** (sem a pasta — caminhos do OneDrive passavam
de 255 caracteres). Com `--origem "nome"` você escolhe um nome amigável. Webcam vira
`webcam_0`; em URLs de câmera (rtsp/http) usuário e senha **não** são gravados.
O valor é sempre limitado a 255 caracteres. Bancos antigos ganham a coluna nas
tabelas `eventos` e `analise_risco` automaticamente na próxima execução.

### Tempo de cada quadro

- **Arquivo de vídeo:** tempo = início + quadro ÷ fps (tempo do vídeo). Assim a
  velocidade não depende da velocidade de processamento do computador.
- **Webcam/stream (ao vivo):** relógio do computador.

Antes desta correção o relógio era usado sempre: processando a ~2,3 FPS um vídeo de
~30 FPS, cada quadro "durava" ~0,44 s em vez de ~0,033 s e as velocidades saíam
~13x menores. **Os números de velocidade da validação abaixo precisam ser refeitos.**
Se o arquivo não informar o FPS, usa `FPS_PADRAO` (30).

### Como calibrar

**Por que homografia.** O fator único (`--calib-p1/p2/dist`) assume a mesma escala
em toda a imagem e em todas as direções. Numa câmera inclinada isso falha: o mesmo
objeto vale menos pixels ao fundo, e deslocamentos ao longo da via encolhem
(escorço) muito mais que a largura. Calibrar com a largura de uma pista e usar esse
fator para velocidade subestima a velocidade — numa simulação com câmera a 8 m de
altura e 35° de inclinação, o erro foi de cerca de 20% (perto) a 80% (longe) para
baixo (ver `tests/test_state_homografia.py`). A homografia usa 4 pontos do chão e
corrige a perspectiva; velocidade e distância passam a ser medidas no plano do chão,
no ponto de contato do veículo (base da caixa), em metros.

**Passo a passo (ferramenta de clique):**

1. Escolha um quadro nítido (para stream ao vivo, salve um quadro `.jpg` na
   resolução original; não use print da janela).
2. Escolha 4 pontos NO CHÃO que formem um retângulo real, com largura e comprimento
   que você consiga medir (Google Maps em satélite, ou medidas padrão da via).
   Quanto MAIOR o retângulo e quanto mais ele cobrir por onde os veículos passam,
   melhor. Numa simulação (câmera sintética, só erro de clique de ±2 px, medidas
   reais perfeitas), o erro mediano dentro da área calibrada ficou em 1–2%; medindo
   bem além da borda mais distante do retângulo, subiu para cerca de 3–4% com um
   retângulo grande (3,5 × 20 m) e 5–10% com um pequeno (3,5 × 8 m), com casos de
   10–30%. Com erro de clique de ±5 px tudo piora. Erros nas medidas reais
   (Google Maps, valores padrão) somam-se a esses.
3. `python ferramenta_calibracao.py --source quadro.jpg --saida calibracao_resultado.json`
4. Tecla `h`, clique P1 perto-esq, P2 perto-dir, P3 longe-dir, P4 longe-esq; tecla `k`;
   digite largura (P1→P2) e comprimento (P2→P3) em metros.
5. Confira a grade (`g`): as linhas devem ficar paralelas às bordas e faixas da rua.
6. **Valide** (`v`): meça uma distância que você conheça e que NÃO usou na calibração
   (ex.: outra largura de pista). Se o erro passar de uns 5–10%, refaça os pontos.
7. `q` salva. Rode: `python main.py --source video.mp4 --calib-arquivo calibracao_resultado.json`
   (o mesmo arquivo guarda as zonas: acrescente `--zonas calibracao_resultado.json`).

A calibração vale para UMA câmera numa posição fixa. Se a câmera mexer, recalibre. Se
o vídeo tiver resolução diferente da usada na calibração (mesma proporção), o sistema
ajusta a matriz automaticamente; se a proporção mudar, ele avisa e pede recalibração.

**Limitações a declarar no TCC:** a homografia vale só para o plano do chão (ruas com
rampa/declive degradam); depende da precisão dos cliques e das medidas reais; a base da
caixa do detector é uma aproximação do ponto de contato (sombras, oclusões e caixas
cortadas na borda aumentam o erro); fora da área calibrada o erro cresce.

### Como configurar zonas de risco

1. Copie `zonas_exemplo.json` e edite as coordenadas (em pixels, do frame do vídeo).
2. Cada zona é um polígono: lista de pontos `[x, y]`, na ordem (não precisa fechar
   o polígono repetindo o primeiro ponto no fim).
3. Passe o arquivo com `--zonas caminho/para/zonas.json`.
4. Quando um veículo rastreado entra em uma zona pela primeira vez (ou reentra
   depois de sair), um evento `entrada_zona_risco` é salvo na tabela `eventos`,
   já com a velocidade e distância estimadas naquele momento.

## O que muda em relação aos scripts antigos

- Um único módulo, sem duplicação de lógica entre os três arquivos anteriores.
- Sem senha nem caminho de vídeo hardcoded no código.
- Tracking usa o ByteTrack nativo do Ultralytics (`tracker="bytetrack.yaml"`) em vez de reimplementar contagem manual de IDs.
- Cada detecção é salva no banco com posição (x, y), velocidade estimada e distância até o veículo mais próximo no frame.
- Velocidade e distância só são calculadas com calibração; sem ela, o sistema avisa e segue funcionando (distância cai para pixels, velocidade fica `None`). A distância em pixels é só informativa: **não gera `proximidade_perigosa` nem entra no score**, porque pixels não são comparáveis ao limiar em metros.
- Zonas de risco são configuráveis por JSON, sem precisar mexer no código; entrada em zona vira evento no banco.
- Score de risco (0-100, baixo/médio/alto) combina velocidade elevada, proximidade perigosa e zona de risco, salvo por track_id na tabela `analise_risco`. Cada veículo é desenhado na tela com cor por nível de risco (verde/laranja/vermelho).
- A lógica de histórico/zona/score vive em `state.py`, separada de `main.py`, para não depender de YOLO nem do banco — dá pra testar isoladamente.

## Limiares e pesos do score (ajustáveis)

```bash
export LIMIAR_VELOCIDADE_KMH=60       # acima disso -> evento "velocidade_elevada"
export LIMIAR_DISTANCIA_MINIMA_M=2.0  # abaixo disso -> evento "proximidade_perigosa"
```

Pesos (em `config.PESOS_RISCO`): velocidade_elevada=30, proximidade_perigosa=25, zona_risco=15, mudanca_brusca=15, aproximacao_rapida=15 (soma = 100). Faixas: 0-29 baixo, 30-59 médio, 60-100 alto. São parâmetros experimentais — devem ser justificados/calibrados com os testes reais (seção de avaliação do TCC), não tratados como valores definitivos.

### Tendência: `mudanca_brusca` e `aproximacao_rapida`

Analisam os últimos `JANELA_TENDENCIA` quadros (padrão 6) e **só funcionam com calibração**:

- `mudanca_brusca`: a janela é dividida em duas metades; vira evento se o ângulo entre
  elas for ≥ `LIMIAR_MUDANCA_DIRECAO_GRAUS` (45°) — só se cada metade andou pelo menos
  `MIN_DESLOCAMENTO_DIRECAO_M` (0,5 m), para o tremor da caixa não virar "curva" —
  ou se a variação de velocidade for ≥ `LIMIAR_ACELERACAO_M_S2` (6 m/s², freada/arrancada).
- `aproximacao_rapida`: a distância ao vizinho mais próximo cai a ≥ `LIMIAR_APROXIMACAO_M_S`
  (3 m/s). Só conta enquanto o vizinho for o **mesmo** veículo (troca de vizinho não é aproximação).

**Com homografia (`--calib-arquivo`)**, o histórico de posições, a distância, os parados e a
tendência passam a ser medidos em metros no plano do chão (ponto de contato do veículo),
e não mais em pixels com escala única — a direção de uma curva, por exemplo, deixa de ser
distorcida pela perspectiva.

### Filtro do cálculo de distância

Ficam fora do cálculo de distância/proximidade, nos dois papéis (nem como alvo, nem como vizinho):
- pedestres e bicicletas (`CLASSES_IGNORADAS_DISTANCIA`) — ex.: manequins, bicicleta estacionada.

**Objetos parados** — abaixo de `LIMIAR_PARADO_KMH` (3 km/h) com calibração, ou de
`LIMIAR_PARADO_PX_S` (20 px/s) sem calibração, olhando os últimos `MIN_PONTOS_PARADO`
(5) quadros; um objeto que acabou de aparecer ainda conta (não dá para afirmar que está
parado) — têm dois modos, escolhidos por `--parados` (ou `PARADOS_NA_DISTANCIA`):

| Modo | Parado como alvo | Parado como vizinho | Efeito |
|---|---|---|---|
| `alvo_e_vizinho` (padrão) | não | não | Ignora carro estacionado e fila parada. Uma moto que passa rente a carros parados **não** gera proximidade. |
| `so_alvo` | não | **sim** | Moto em movimento perto de carro parado gera `proximidade_perigosa` (e `aproximacao_rapida` se se aproxima rápido). Dois carros parados colados continuam sem evento. |

Cuidado com `so_alvo`: pode gerar evento quando a moto passa por carros estacionados à
beira da rua (mais "passou perto de objeto fixo" do que conflito entre veículos). Para
comparar os modos no mesmo vídeo, use `--origem` diferente em cada execução, por exemplo
`--origem cong_alvo_e_vizinho` e `--origem cong_so_alvo`, e compare no filtro do dashboard.

## Testes automatizados

```bash
pip install pytest
python -m pytest tests/ -v
```

196 testes cobrindo calibração (simples e por homografia: matemática, ajuste de resolução, integração com o pipeline e ferramenta de clique), velocidade, distância, point-in-polygon, transições de zona, detecção de eventos de risco, score (inclusive fronteiras exatas 29/30 e 59/60), tendência (mudança brusca e aproximação rápida), tempo do quadro e nome da origem, filtro de pedestres/bicicletas/parados na distância (inclusive o modo `so_alvo`), filtro de presença mínima de motos e as consultas do dashboard (inclusive o filtro por vídeo) (testadas com sqlite como substituto portável do Postgres). Veja `TESTES.md` para o guia completo, incluindo os testes manuais que precisam do YOLO/vídeo real.

## Validação com vídeo real

Rodado com o `vídeo_moto.mp4` e `yolov8m.pt` reais do projeto (450 frames, banco Postgres real, calibração real com faixa de rolamento):
- **Detecção na imagem de teste:** 5/5 motos visíveis detectadas, confiança 0.78–0.91.
- **Tracking no vídeo:** 10 `track_id` de moto surgiram ao todo, mas 3 deles apareceram em 1 frame só (ruído — falso positivo isolado ou troca de ID momentânea).
- **Correção aplicada:** `MIN_FRAMES_PRESENCA_MOTO` (padrão 3) — só conta como moto confirmada quem aparece nesse mínimo de frames. Resultado: **7 motos confirmadas** de 10 IDs brutos, os 3 de ruído corretamente descartados.
- **Desempenho:** ~0,44s/frame (2,3 FPS) em CPU sem GPU — considerar isso na seção de desempenho do TCC; em GPU deve ser bem mais rápido.
- **Cenário do vídeo:** congestionamento (trânsito parado/lento). Velocidades ficaram próximas de 0 (esperado), e 181 eventos de `proximidade_perigosa` foram gerados (veículos muito próximos uns dos outros, comum em engarrafamento). Nenhum evento `velocidade_elevada` — coerente com o cenário.
- **⚠️ Refazer:** essa rodada usou como escala a largura de uma faixa (escala única, que subestima a velocidade ao longo da via em câmera inclinada — ver "Como calibrar") e o relógio do computador como tempo do quadro (velocidades ~13x menores) e contava veículos parados na proximidade. Com as correções desta versão, rodar de novo com `--origem congestionamento` — a expectativa é que a maior parte dos 181 eventos de `proximidade_perigosa` desapareça (veículos parados agora são ignorados).
- **Nível de risco:** 8630/8630 registros em "baixo" — esperado, já que `proximidade_perigosa` sozinha (peso 25) não atinge o limiar de "médio" (30). Para ver níveis mais altos, é necessário configurar zonas de risco (`--zonas`) ou usar um vídeo com trânsito fluindo mais rápido.

## Dashboard

```bash
streamlit run dashboard.py
```

Abre no navegador, lendo diretamente do banco (precisa das mesmas variáveis de ambiente `DB_*` configuradas). Na barra lateral há um filtro **Vídeo / origem** (todos os vídeos ou um específico). Mostra: total de detecções, veículos únicos, motos confirmadas, eventos de risco (total e "alto"), velocidade média, distribuição de nível de risco, eventos por tipo, detecções por tipo de veículo, evolução dos eventos no tempo e mapa de calor das posições das motos no quadro.

Não roda detecção nem tracking — só visualiza o que o `main.py` já salvou. Rode o `main.py` num vídeo primeiro, depois o dashboard.

A lógica de consulta (`dashboard_queries.py`) é separada da interface (`dashboard.py`) de propósito — mesmo padrão do `state.py` — para poder ser testada sem depender de tela nem de um Postgres real (os testes usam sqlite como substituto para as consultas portáveis).

## Próxima etapa

Calibrar por homografia as câmeras/vídeos usados e refazer o teste do congestionamento (tempo do vídeo + homografia); novos vídeos/demonstrações. O MVP do prompt mestre do TCC está completo: YOLO → Tracking → Velocidade → Distância → Zona de risco → Tendência → Score → PostgreSQL → Dashboard.
