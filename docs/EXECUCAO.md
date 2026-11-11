# Guia de execução

Todos os comandos são executados na raiz do projeto (por exemplo, no Git Bash ou no PowerShell). Para ver todos os parâmetros de um programa: `python programa.py --help`.

## 1. Instalação e configuração

```bash
pip install -r requirements.txt
```

Variáveis de ambiente (as principais):

| Variável | Padrão | Função |
|---|---|---|
| `DB_HOST`, `DB_NAME`, `DB_USER` | `localhost`, `projeto_motos`, `postgres` | Conexão com o PostgreSQL |
| `DB_PASSWORD` | — (obrigatória) | Senha do banco; sem valor padrão de propósito |
| `YOLO_MODEL_PATH` | `yolov8m.pt` | Pesos do detector |
| `CONF_THRESHOLD` | `0.3` | Confiança mínima do YOLO |
| `LIMIAR_DISTANCIA_MINIMA_M` | `2.0` | Distância de `proximidade_perigosa` |
| `LIMIAR_VELOCIDADE_KMH` | `60` | Limiar de `velocidade_elevada` |
| `LIMIAR_MUDANCA_DIRECAO_GRAUS` / `LIMIAR_ACELERACAO_M_S2` | `45` / `6.0` | Mudança brusca |
| `JANELA_TENDENCIA` | `6` | Janela (quadros) de tendência |
| `EVENTOS_INFORMATIVOS` | `velocidade_elevada,mudanca_brusca` | Eventos **não** registrados (`""` os registra) |

PowerShell: `$env:DB_PASSWORD = "sua_senha"`. Bash: `export DB_PASSWORD=sua_senha`.

## 2. Estabilização de vídeos gravados em mãos

Necessária só quando a câmera não é fixa. O vídeo é alinhado a um quadro de referência (ORB + RANSAC), com limites de 3% de escala e 3° de rotação.

```bash
# 1) medir o movimento e sugerir trechos
python estabilizar_video.py --entrada "video.mp4" --analisar
# 2) estabilizar um trecho (quadros inicial e final) usando um quadro de referência
python estabilizar_video.py --entrada "Ligação Leste-Oeste São Paulo.mp4" --saida L_est.mp4 --referencia 598 --inicio 300 --fim 1170
```

## 3. Calibração por homografia

A calibração leva pixels a metros no plano da via e vale para **uma câmera numa posição fixa** (ou um vídeo estabilizado).

1. Salve um quadro nítido do vídeo, na resolução original (`*_referencia.jpg`).
2. Marque pontos no chão com coordenadas reais conhecidas (marcações viárias de dimensões padronizadas) e escreva o CSV `nome;px;py;x_m;y_m` (campo vazio = coordenada livre, restrição parcial). A ferramenta de clique ajuda a marcar: `python calibrar_por_pontos.py --pontos pontos.csv --marcar --imagem referencia.jpg`.
3. Calcule a homografia, com conferência visual e validações independentes (medidas que **não** entraram no ajuste):

```bash
python calibrar_por_pontos.py --pontos calibracoes/pontos_L.csv --imagem calibracoes/L_referencia.jpg --saida calibracoes/calib_L.json --conferencia calibracoes/conf_L.jpg
# opcional: --validacao x1,y1,x2,y2,distancia_m  (repetível)  e  --transversais-horizontais
```

Confira o RMS e o erro das validações: se passarem de uns 5–10%, refaça os pontos. Fora da área calibrada o erro cresce (nos vídeos do trabalho, o limite útil ficou perto de 30 m).

Alternativa interativa (4 pontos, retângulo no chão): `python ferramenta_calibracao.py --source quadro.jpg --saida calibracao_resultado.json`.

## 4. Processamento de vídeo

```bash
# vídeo L (calibrado, faixa de análise em metros: x_min,x_max,y_min,y_max)
python main.py --source L_est.mp4 --calib-arquivo calibracoes/calib_L.json --origem leste_oeste --faixa-analise "-0.5,9.5,-5,30"

# vídeo S (pista central)
python main.py --source S_est.mp4 --calib-arquivo calibracoes/calib_S.json --origem anhanguera_shopping --faixa-analise "-3.8,3.8,-5,40"

# imagem, sem abrir janela, com zonas de risco
python main.py --source moto_teste.jpg
python main.py --source video.mp4 --calib-arquivo calibracoes/calib_X.json --zonas zonas_exemplo.json --no-display
```

Parâmetros úteis de `main.py`:

| Parâmetro | Função |
|---|---|
| `--source` | Arquivo, imagem, `0` (webcam) ou URL |
| `--origem` | Nome gravado no banco e usado no filtro do dashboard (máx. 255 caracteres) |
| `--calib-arquivo` | JSON de homografia (prioridade sobre `--calib-p1/--calib-p2/--calib-dist`, calibração simples de fator único) |
| `--faixa-analise` | Só analisa veículos com ponto de contato nessa faixa do chão (m) |
| `--zonas` | JSON de zonas de risco (polígonos em pixels) |
| `--parados` | `alvo_e_vizinho` (padrão) ou `so_alvo`: papel dos objetos parados na distância |
| `--limiar-velocidade` | Limite de velocidade (km/h) |
| `--batch-size` | Registros por gravação no banco (padrão 30) |
| `--no-display` | Não abre janela |

Para fechar a janela: tecla `q`. O que já foi processado é salvo.

**Tempo de cada quadro.** Em arquivo, tempo = início + quadro ÷ fps (independe da velocidade de processamento). Em webcam/URL, usa o relógio do computador. Cada registro guarda `origem_video`; use uma origem diferente por execução para comparar no dashboard.

## 5. Dashboard

```bash
streamlit run dashboard.py
```

Lê direto do banco (mesmas variáveis `DB_*`) e tem filtro **Vídeo / origem**. Não roda detecção: processe um vídeo primeiro.

## 6. Testes

```bash
python -m pytest
```

295 testes automatizados (calibração, velocidade, distância, predição, eventos, score, filtros, consultas do dashboard). Ver `TESTES.md`.

## 7. Câmeras e transmissões ao vivo

O sistema não depende de o vídeo ser um arquivo: `--source` aceita webcam, URL de transmissão e câmeras IP, e cada fonte recebe um nome em `--origem`, o que permite várias cenas no mesmo painel.

```bash
# webcam do computador
python main.py --source 0 --origem webcam_teste

# câmera IP (RTSP/HTTP). Usuário e senha da URL NÃO são gravados no banco
python main.py --source "rtsp://usuario:senha@192.168.0.10/stream" --origem camera_portaria --calib-arquivo calibracoes/calib_camera.json

# transmissão pública (ex.: YouTube) com yt-dlp
yt-dlp -g -f "bv[height<=720]" "https://www.youtube.com/watch?v=ID_DO_VIDEO"
python main.py --source "URL_RETORNADA" --origem camera_x --calib-arquivo calibracoes/calib_X.json
```

Para uma câmera fixa: (1) salve um quadro `.jpg` na resolução original, (2) calibre como na seção 3 e (3) informe `--calib-arquivo`. Se a câmera for movida, recalibre.

**Pontos de atenção** (a capacidade ao vivo **não foi avaliada quantitativamente** neste trabalho):
- **Calibração:** vale para câmera fixa; os vídeos do trabalho foram gravados em mãos e estabilizados em pós-processamento, o que não é possível em tempo real.
- **Desempenho:** em CPU, o YOLOv8m processou cerca de 2,3 quadros por segundo, insuficiente para tempo real; o desempenho com GPU não foi medido. Alternativas: modelo menor, redução de resolução ou de quadros por segundo.
- **Dados:** a gravação contínua gera volume que exige política de retenção.
- **Privacidade:** câmeras de terceiros exigem autorização e observância da LGPD; o sistema grava posições e identificadores de rastreamento, não imagens.
- **Fontes não testadas:** RTSP e URLs de transmissão dependem do suporte do OpenCV e do provedor; não foram avaliadas.

Trabalhos futuros: medir o desempenho em GPU, avaliar uma câmera fixa em tempo real, ajustar o detector (*fine-tuning*) com dados de trânsito brasileiro e substituir a extrapolação por um modelo de trajetória aprendido.

## 8. Reproduzir os resultados da monografia

1. Coloque os vídeos A, B, S e L na raiz (não estão no repositório); estabilize-os (seção 2) e use as calibrações de `calibracoes/`.
2. Faça `TRUNCATE` das tabelas se quiser partir de um banco limpo.
3. Processe cada vídeo com sua `--origem` e `--faixa-analise` (seção 4) e abra o dashboard.
4. Os eventos avaliados no gabarito estão no Apêndice C da monografia.
