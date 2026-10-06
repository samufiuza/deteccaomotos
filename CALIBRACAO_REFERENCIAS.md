# Referências padrão para calibração (sem acesso físico ao local)

Valores oficiais/reconhecidos, com fonte, para usar como "distância real conhecida"
na ferramenta de calibração — sem precisar saber onde o vídeo foi gravado.

## ATENÇÃO: largura de pista serve como medida do retângulo, não como escala única

Uma versão anterior deste documento recomendava marcar dois pontos na largura de uma
faixa e usar esse valor como fator único de escala (`--calib-p1/p2/dist`). Isso só é
adequado para câmera quase de cima. Em câmera inclinada, a escala lateral não vale
para movimento ao longo da via, e a velocidade sai subestimada (numa simulação, de
cerca de 20% a 80% abaixo do real, conforme a profundidade). Use a **calibração por
homografia** (`ferramenta_calibracao.py`, tecla `h`; ver README) e use as medidas
abaixo como dimensões do retângulo do chão.

## Como obter as medidas do retângulo (sem acesso físico ao local)

Você precisa de 4 pontos do chão que formem um retângulo real, e de largura e
comprimento em metros:

- **Google Maps / Earth, vista de satélite, régua ("Medir distância")**: é o melhor
  caminho quando se sabe onde a câmera fica (ex.: a página da câmera costuma informar
  as coordenadas). Meça entre feições visíveis nas duas imagens (câmera e satélite),
  como cantos de calçada, faixas de pedestres e eixos de cruzamentos.
- **Medidas padrão da via**, quando o local é desconhecido: largura de faixa de
  rolamento de 3,00 a 3,50 m (valor usual; ver tabela abaixo). Serve para a LARGURA do
  retângulo. O COMPRIMENTO é mais difícil de obter por padrão; use feições conhecidas
  (vão entre faixas de pedestres, por exemplo) ou o Google Maps.
- **Quanto maior o retângulo, melhor**, desde que cubra por onde os veículos passam.
- Sempre **valide** (tecla `v`) medindo uma distância que não usou na calibração.

**Fonte para citar:** Manual de Sinalização Urbana da CET-SP (volume 5, sinalização
horizontal) e a Resolução CONTRAN nº 973/2022, que instituiu o Regulamento de
Sinalização Viária e revogou a Resolução CONTRAN nº 236/2007. Declare no TCC que as
medidas são valores padrão ou medições remotas, e não medições no local.

## Outras referências oficiais disponíveis (caso a via mude ou outro vídeo seja usado)

| Referência | Valor | Fonte | Observação |
|---|---|---|---|
| Faixa de rolamento (largura) | 3,00–3,50 m | Manual CET-SP / Res. CONTRAN 973/2022 | melhor para vídeos com via de cima, várias faixas visíveis |
| Faixa de pedestres (largura de cada listra) | 0,30–0,40 m | Manual de Sinalização Horizontal CONTRAN/DNIT | útil se houver faixa de pedestres nítida no quadro; contar quantas listras aparecem pra somar a largura total |
| Placa Mercosul de carro | 0,40 m (largura) x 0,13 m (altura) | Resolução CONTRAN nº 969/2022 | mais precisa, mas só funciona se a placa aparecer grande/nítida na imagem (poucos pixels = mais erro relativo) |
| Placa Mercosul de moto | 0,20 m (largura) x 0,17 m (altura) | Resolução CONTRAN nº 969/2022 | mesma ressalva da placa de carro, ainda mais exigente (moto é menor no quadro) |
| Comprimento médio de carro de passeio | ~4,3–4,5 m | Estimativa geral (não é norma oficial de trânsito) | usar só se nenhuma das opções acima estiver visível — é a menos rigorosa de citar |

**Como justificar no TCC:** citem a fonte oficial (CONTRAN) e declarem explicitamente
que a medida usada é um valor padrão de referência, não uma medição no local —
isso é uma escolha metodológica válida quando não há acesso físico à via, e deve
constar na seção de limitações, junto com a precisão da calibração (erro de clique
nos 4 pontos, erro das medidas remotas e queda de precisão fora da área calibrada).
