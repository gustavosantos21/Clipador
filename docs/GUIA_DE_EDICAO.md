# Guia de edição do Clipador

Padrões que o agente segue ao transformar material bruto em conteúdo. São o "manual de estilo" — ajuste aqui quando quiser mudar o jeito que os vídeos saem.

## 1. Formatos

| Destino | Preset | Duração ideal | Enquadramento padrão | Legenda |
|---|---|---|---|---|
| YouTube Shorts | `shorts` | 25–55 s (máx 60) | `crop` no rosto de quem fala | `bold_pop` |
| Instagram Reels | `reels` | 20–45 s (máx 90) | `crop` | `bold_pop` |
| TikTok | `tiktok` | 20–60 s | `crop` | `bold_pop` ou `one_word` |
| Feed Instagram | `feed45` | 15–45 s | `crop` | `highlight_green` |
| YouTube longo | `youtube` | conforme o conteúdo | original 16:9 | `clean_box` (opcional) |

Um mesmo trecho bom normalmente vira **3 arquivos**: `shorts`, `reels` e `tiktok` (mesma receita trocando `preset` e `output`).

## 2. Estrutura de um corte curto

1. **Gancho (0–3 s)** — a frase mais forte, curiosa ou polêmica do trecho vai PRIMEIRO, mesmo que no bruto ela apareça depois. Na receita isso é só um segmento extra no início.
2. **Contexto (3–10 s)** — o mínimo para entender o gancho.
3. **Desenvolvimento** — a história/explicação, sem enrolação. Corte toda repetição, “né”, “tipo”, “então…”, falsos começos.
4. **Payoff** — a conclusão/punchline. O vídeo termina logo depois dela (no máximo 0,5 s de respiro). Nada de “é isso galera”.

Critérios para escolher trechos no bruto:
- Faz sentido **sem o resto do vídeo**.
- Tem emoção (risada, indignação, revelação, número surpreendente, opinião forte) — os `energy_peaks` da análise ajudam a achar.
- Uma ideia por clipe.

## 3. Ritmo

- `remove_silence` ligado em fala (talking head, podcast, aula). `min_silence` 0.35–0.5 s, `pad` 0.10–0.15 s. Desligue em trechos de música/ação.
- Mudança visual a cada **3–6 s**: zoom punch-in (`ramp: 0`, scale 1.15–1.3) nas frases de ênfase, alternando com zoom suave (`ramp: 0.3–0.6`).
- Não dar zoom em dois trechos seguidos com a mesma escala.
- Transição: corte seco (`none`) é o padrão. Use `fade`/`slideup` só entre blocos de assunto diferente ou em vídeos longos.

## 4. Enquadramento vertical

- Uma pessoa falando: `crop` com `x` no rosto (olhos ≈ 1/3 do topo — use `y` 0.3–0.45 se o bruto for alto).
- Duas pessoas (podcast): troque o `x` por segmento conforme quem fala, ou keyframes em `x`.
- Tela/jogo + webcam: `split` (webcam em cima, `ratio` 0.35–0.45).
- Slide, gráfico ou algo que não pode ser cortado: `blur`.
- Sempre conferir a folha de contato do resultado (`--preview`) para ver se ninguém ficou cortado.

### Streams (GTA e jogos em geral)

- Layout padrão: `{"mode": "stream", "facecam": "auto"}` — webcam em cima (38%), jogo embaixo. Confira `facecam.jpg`; se a caixa amarela não bater com a webcam, passe o `rect` manual.
- Se a ação do jogo está fora do centro (ex.: minimapa, carro à direita), ajuste `game_x`. Em perseguição/tiroteio, `game_zoom` 1.1–1.25 deixa mais legível no celular.
- Momento sem reação do streamer (só jogo) → `{"mode": "crop", "x": 0.5}` ou `blur`.
- Streamer sem webcam → `{"mode": "crop", "x": "auto"}` não ajuda (não há rosto); use `crop` no centro da ação.

## 5. Texto e legendas

- **Legenda sempre ligada** em vídeo curto (a maioria assiste sem som). Máx 3 palavras por bloco, caixa alta, contorno grosso.
- Posição `lower` (≈ 24% acima da base) para não ficar embaixo dos botões/descrição do TikTok/Reels. Nada importante nos 15% inferiores nem nos 10% superiores.
- **Título do gancho** (`texts`) nos primeiros 2–3 s, no topo, até 5 palavras, com `box`.
- Corrigir nomes próprios e termos errados da transcrição com `captions.replace`.

## 6. Áudio

- Loudness final −14 LUFS (padrão do preset).
- Música de fundo opcional, `volume` 0.06–0.12 com `duck: true` (abaixa sozinha quando há fala).
- Efeitos sonoros (whoosh, pop) só em transições e zooms secos, `volume` ≤ 0.6.

## 7. Overlays da marca

Coloque os arquivos em `assets/overlays/` e descreva aqui como usá-los. Sugestão inicial:

| Overlay | Arquivo | Onde | Quando |
|---|---|---|---|
| Logo/marca d'água | `assets/overlays/logo.png` | `top-right`, `width` 0.16, `opacity` 0.85 | vídeo todo |
| CTA "Siga" | `assets/overlays/cta_siga.mov` | `bottom`, acima da legenda | últimos 3 s |
| Moldura | `assets/overlays/moldura.png` | `fullscreen: true` | vídeo todo |

## 8. Clipes de stream de GTA

- **O que vira clipe:** fail engraçado, perseguição/fuga improvável, reação exagerada do streamer, glitch, momento de RP (roleplay) com fala marcante, conquista difícil, interação com chat/doação.
- **Gancho:** comece no lance (ou 1–2 s antes); se precisar de contexto, ponha o pico como gancho e volte (segmento repetido).
- **Duração:** 20–40 s. Clipe de stream envelhece rápido — publicar no mesmo dia vale mais que perfeição.
- **Título na tela:** curto, curioso, sem spoiler do final (“ele achou que ia dar certo…”).
- **Crédito:** nome do streamer na tela (overlay/texto pequeno) e na descrição.
- **Série/formatos:** “melhores momentos do dia”, “top 5 da semana” (vários candidatos numa receita), “reação do streamer a …”.

## 9. Checklist antes de entregar

- [ ] Gancho nos primeiros 3 s
- [ ] Duração dentro do limite da plataforma
- [ ] Ninguém cortado no enquadramento (ver preview)
- [ ] Legenda sem erro de nome próprio
- [ ] Sem silêncio morto, sem final arrastado
- [ ] Áudio audível e sem estourar
