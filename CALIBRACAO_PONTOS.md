# Calibração por vários pontos do chão (Google Earth Pro)

Use quando não há um retângulo medível na cena. Cada ponto precisa aparecer
no quadro da câmera e no Google Earth Pro (pontas de traços de faixa, cantos
de faixa de pedestres, quinas de meio-fio).

## 1. Marcar os pontos no quadro
    python calibrar_por_pontos.py --marcar --imagem balneario_frame.jpg --pontos pontos.csv
Clique nos pontos (u desfaz, q salva). Gera `pontos.csv` com lat/lon em branco.

## 2. Ler lat/lon no Google Earth Pro
Ferramentas > Opções > Visualização 3D > Mostrar Lat/Long: **Graus decimais**.
Passe o cursor sobre cada ponto e leia lat/lon no rodapé. Preencha o CSV
(separador `;`, vírgula decimal é aceita):

    nome;px;py;lat;lon
    P1;482;423;-26,99xxxx;-48,63xxxx

## 3. Calibrar e validar
    python calibrar_por_pontos.py --pontos pontos.csv --imagem balneario_frame.jpg \
        --saida calib_balneario.json --validacao 482,423,590,482,4.00 \
        --conferencia conferencia.jpg

- RMS <= 0,5 m: boa; <= 1,0 m: aceitável; acima: revisar pontos.
- Com 6+ pontos o script aponta o ponto suspeito.
- Valide com medidas que NÃO entraram no ajuste.
- Pontos devem cobrir perto e longe da câmera, e NÃO ficar todos numa linha.

Depois: `python main.py --source <video> --calib-arquivo calib_balneario.json`

## Comparando trena x satélite (mesma cena)
1. Calibre com trena: `python ferramenta_calibracao.py --source video.mp4 --frame N --saida calib_trena.json`
2. Calibre por satélite: marque os pontos (`--marcar`), preencha lat/lon e rode o passo 3 com `--saida calib_satelite.json`
3. Use a MESMA distância de validação (não usada no ajuste) nas duas e compare o erro percentual.
4. Fique com a de menor erro e registre as duas na monografia.
Para um vídeo seu, use `--marcar` para gerar o CSV com os pixels do seu quadro
(o `pontos_balneario_modelo.csv` tem pixels do quadro de Balneário).
