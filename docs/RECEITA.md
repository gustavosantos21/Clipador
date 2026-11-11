# Receita de edição (spec JSON) — referência

Cada vídeo final é descrito por **um arquivo JSON**. O agente escreve a receita e o Clipador renderiza com `python -m clipador render receita.json`.

**Regra de ouro dos tempos:**
- `segments[].start/end`, `zooms[]`, keyframes de `reframe.x/y` → **tempo do arquivo BRUTO** (o mesmo da transcrição).
- `texts[]`, `overlays[]`, `audio.sfx[].at` → **tempo do vídeo FINAL** (0 = primeiro frame do clipe).

Tempos aceitam `83.5`, `"01:23.5"` ou `"00:01:23.500"`.

## Exemplo completo

```json
{
  "title": "Clipe 01 — a história do primeiro cliente",
  "source": "raw/podcast_ep12.mp4",
  "output": "out/ep12/clip01_shorts.mp4",
  "preset": "shorts",
  "reframe": {"mode": "crop", "x": 0.35},
  "remove_silence": {"min_silence": 0.45, "pad": 0.12},
  "segments": [
    {"start": "12:03.2", "end": "12:09.8", "label": "gancho"},
    {"start": "10:41.0", "end": "11:20.5",
     "zooms": [{"start": "11:02.1", "end": "11:05.0", "scale": 1.25, "ramp": 0}]}
  ],
  "transition": {"type": "none"},
  "texts": [
    {"text": "ELE QUASE DESISTIU", "start": 0, "end": 2.5, "position": "top", "box": true}
  ],
  "overlays": [
    {"file": "assets/overlays/logo.png", "position": "top-right", "width": 0.18, "opacity": 0.9}
  ],
  "captions": {"transcript": "projects/ep12/work/transcript.json", "style": "bold_pop",
               "replace": {"clipador": "Clipador"}},
  "audio": {"normalize": true, "lufs": -14,
            "music": {"file": "assets/music/lofi.mp3", "volume": 0.08, "duck": true},
            "sfx": [{"file": "assets/sfx/whoosh.wav", "at": 6.4, "volume": 0.6}]},
  "fade_out": 0.4
}
```

## Campos do topo

| campo | descrição |
|---|---|
| `source` | arquivo bruto padrão dos segmentos |
| `output` | caminho do .mp4 final |
| `preset` | `shorts`, `reels`, `tiktok`, `vertical`, `youtube`, `youtube4k`, `feed45`, `square` (`python -m clipador presets`) |
| `width`/`height`/`fps` | sobrepõem o preset |
| `quality` | `final` (padrão) ou `draft` |
| `reframe` | enquadramento padrão (ver abaixo) |
| `remove_silence` | `true` ou `{threshold_db, min_silence, pad}` — corta pausas (jump cut) dentro de cada segmento |
| `segments` | lista de trechos, na ordem em que aparecem no vídeo final |
| `transition` | `{"type": "none"}` (corte seco) ou tipo do xfade: `fade`, `fadeblack`, `slideleft`, `slideup`, `circleopen`, `smoothleft`, … + `duration` |
| `texts` | títulos/ganchos desenhados na tela |
| `overlays` | imagens/vídeos por cima (logo, moldura, CTA, emoji, lower third) |
| `captions` | legendas automáticas a partir da transcrição |
| `audio` | normalização, música com ducking, efeitos sonoros |
| `fade_in` / `fade_out` | fade de vídeo e áudio (s) no início/fim |

## `segments[]`

| campo | descrição |
|---|---|
| `start`, `end` | tempo no bruto (`end` omitido = até o fim). Para imagem (`.png`), `end` = duração |
| `source` | outro arquivo (ex.: vinheta de intro/outro) |
| `speed` | 0.25–4 (áudio acompanha sem mudar o tom) |
| `reframe` | sobrepõe o enquadramento só neste trecho |
| `zooms` | `[{start, end, scale=1.25, x=0.5, y=0.45, ramp=0.25}]` — `ramp: 0` = punch-in seco |
| `remove_silence` | sobrepõe o global (`false` desliga) |
| `mute`, `volume` | áudio do trecho |
| `label` | nome livre (aparece em erros) |

## `reframe` — modos

- **`crop`** (preencher): corta para o formato de saída. `x`, `y` de 0 a 1 = posição do corte (0 = esquerda/topo). `x` pode ser keyframes em tempo do bruto: `[["10:41", 0.3], ["10:48", 0.7]]` para acompanhar quem fala.
  - **`"x": "auto"`** — detecção de rosto: segue a pessoa como um operador de câmera (fica parado enquanto o rosto está na zona morta, move suave quando sai). Opções: `step` (intervalo de amostragem, 0.5 s), `deadzone` (0.07). Sem rosto detectado → centro. `scale: 1.2` aperta o enquadramento. `rect: [x,y,w,h]` recorta uma região do bruto antes.
- **`blur`**: vídeo inteiro no meio, fundo desfocado (bom para conteúdo 16:9 em 9:16 quando não dá pra cortar). Opções: `fg_y` (`"center"` ou fração), `fg_scale`, `fg_max_h`, `blur`, `darken`.
- **`fit`**: vídeo inteiro com barras (`color`).
- **`stream`**: layout de live — **facecam em cima, jogo embaixo**. `facecam: "auto"` detecta a webcam sobreposta (ou `[x,y,w,h]` manual), `ratio` (altura da cam, 0.38), `game_x`/`game_y` (centro do recorte do jogo, 0.5; sem `game_x` o recorte desvia sozinho da webcam — `avoid_facecam: false` desliga), `game_zoom` (1.0), `fallback` (`crop`|`blur`, usado se não houver facecam). Veja o resultado da detecção em `projects/<nome>/work/facecam.jpg`.
- **`split`**: duas regiões do bruto empilhadas. `top` e `bottom` são `[x,y,w,h]` normalizados; `ratio` = altura da parte de cima (ex.: webcam em cima 0.4, jogo/tela embaixo).

## `texts[]`

`{text, start, end, position: top|center|bottom, margin, x, y, size=0.05 (fração da altura), font="Inter Black", color, outline, outline_color, box, box_color, uppercase, fade=0.2}`. Use `\n` para quebrar linha.

## `overlays[]`

`{file, start, end, position: top-left|top|top-right|left|center|right|bottom-left|bottom|bottom-right, margin=0.04, x, y, width (fração da largura ou px), opacity, fullscreen, chromakey: "#00FF00", similarity, blend, loop, above_captions}`

- PNG com transparência ou vídeo `.mov`/`.webm` com alpha funcionam direto.
- Overlay com fundo verde: `"chromakey": "#00FF00"`.
- Moldura que cobre a tela toda: `"fullscreen": true`.

## `captions`

`{transcript, style, source, overrides: {...}, replace: {"errado": "certo"}, enabled, words}`

Estilos em `styles/captions/` (`bold_pop`, `highlight_green`, `one_word`, `karaoke`, `clean_box`). `overrides` muda qualquer campo do estilo (`position`, `size`, `highlight`, `max_words`, `font`…). `words` permite passar palavras já na timeline final (sem transcrição).

## `audio`

`{normalize=true, lufs=-14, music: {file, volume=0.12, duck=true, fade_in, fade_out, start}, sfx: [{file, at, volume}]}`
