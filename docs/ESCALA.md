# Escala: muitas horas de stream → clipes todos os dias

Objetivo inicial: um canal (YouTube Shorts + Reels + TikTok) só com clipes de streams de GTA 6. Uma stream típica tem 4–8 h; vários streamers ou um streamer diário = dezenas de horas por semana. Não dá para transcrever e assistir tudo, então o pipeline é **em funil**: sinais baratos em tudo → processamento caro só no que tem chance.

## Funil

```
VOD (6 h) + chat
   │  1. scan  ─ áudio em blocos (memória constante) + taxa/“hype” do chat        ~1–2 min por hora de VOD
   ▼
30 candidatos (≈ 25 min de material)
   │  2. facecam ─ 40 frames espalhados, uma vez por VOD                          ~20 s
   │  3. transcribe ─ só os candidatos (faster-whisper)                           ~5–15 min em CPU, ~1 min em GPU
   ▼
receitas automáticas (layout stream, legenda, -14 LUFS)
   │  4. agente revisa: lê transcrição, escolhe os 5–10 melhores, põe gancho, título, zooms
   ▼
   │  5. render (fila, N workers em paralelo)                                     ~0,3–1× tempo real por clipe em CPU
   ▼
clipes prontos → revisão humana rápida → publicação
```

Comandos equivalentes:

```bash
python -m clipador scan raw/vod.mp4 --chat raw/vod.chat.json -o projects/vod/work/candidates.json
python -m clipador facecam raw/vod.mp4 --debug projects/vod/work/facecam.jpg
python -m clipador transcribe-ranges raw/vod.mp4 --candidates projects/vod/work/candidates.json -o projects/vod/work/transcript.json
python -m clipador jobs --add pipeline --args '{"file": "vod.mp4", "top_render": 5}'
python -m clipador worker -n 3
```

## O chat é o melhor sinal

Em stream de GTA, o momento clipável quase sempre gera explosão no chat (KEKW, KKKK, “CLIP”, “????”). O scan usa o chat com um atraso de 8 s (o chat reage depois do lance). Coloque o chat ao lado do vídeo com o mesmo nome: `raw/vod.mp4` + `raw/vod.chat.json`.

Formatos aceitos: JSON do TwitchDownloader (`TwitchDownloaderCLI chatdownload`), JSON do chat-downloader, `live_chat.json` do yt-dlp (YouTube), CSV `segundos,mensagem` ou texto `[HH:MM:SS] usuario: msg`.

Sem chat, o scan funciona só com áudio (gritos, risadas, explosões), mas a precisão cai.

## Componentes e como cada um escala

| Etapa | Gargalo | Hoje | Próximo degrau |
|---|---|---|---|
| Ingestão | disco/rede | arquivos em `raw/` (upload pela interface) | `yt-dlp`/TwitchDownloader em job agendado, storage S3/R2 |
| Scan | decodificar áudio | 1 processo ffmpeg por VOD, memória constante | vários VODs em paralelo (1 por worker) |
| Facecam | decodificar ~40 frames | cache em `.cache/faces` | igual (barato) |
| Transcrição | CPU/GPU | faster-whisper `small` int8 só nos candidatos | GPU (`--device cuda`, `large-v3`), 1 worker de GPU dedicado |
| Seleção | atenção humana/agente | agente `clipador-editor` | Claude via API em modo headless lendo `candidates.json` + transcrição e gerando receitas em lote |
| Render | CPU (x264) | fila SQLite + N workers | `h264_nvenc` (GPU) ou várias máquinas; fila em Postgres/Redis |
| Publicação | APIs/limites | manual | YouTube Data API, TikTok Content Posting API, Instagram Graph API com agenda |

A fila (`clipador/jobs.py`) já separa *quem pede* de *quem executa*: a interface e a CLI só enfileiram; `python -m clipador worker -n N` executa. Para várias máquinas, troque o SQLite por Postgres/Redis mantendo `enqueue/claim/update` e coloque `raw/`, `projects/` e `out/` num storage compartilhado.

## Ordem de grandeza (CPU de 4 núcleos, sem GPU)

- Scan de 1 h de VOD: ~1–2 min (dominado pela decodificação do áudio).
- Transcrição de 30 candidatos × 40 s com `small`: ~10 min.
- Render de um short de 45 s, qualidade final: ~1–2 min; rascunho: ~15 s.

Uma máquina com GPU modesta processa confortavelmente várias streams de 6 h por dia.

## Riscos que não são técnicos

- **Permissão do streamer.** Clipar a stream de outra pessoa exige autorização (muitos streamers aceitam canais de clipes, alguns pedem crédito ou divisão). Combine antes e dê crédito no vídeo/descrição.
- **Conteúdo reutilizado (YouTube).** Canais que só repostam trechos sem transformação podem ser recusados na monetização. Gancho próprio, título na tela, legendas, cortes/zooms e montagem (ex.: “top 5 da semana”) contam como transformação.
- **Música na stream.** Música de fundo da live pode gerar Content ID/remoção; o clipe herda o problema.
- **Spoilers/regras do jogo.** Acompanhe as diretrizes da Rockstar/Take-Two para vídeos de gameplay.
