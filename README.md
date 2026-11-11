# Clipador ✂️

Ferramenta para clipar e editar vídeos longos e curtos para YouTube, Shorts, Instagram Reels e TikTok — feita para ser operada por um agente de IA.

**Como funciona:** você entrega o material bruto → o agente analisa, transcreve, escolhe os melhores trechos e escreve uma *receita* JSON para cada vídeo → o Clipador renderiza com ffmpeg (cortes, jump cuts, reenquadramento 9:16, zooms, legendas animadas, títulos, overlays, música com ducking, normalização de áudio).

## Instalação

Requisitos: Python 3.10+ e ffmpeg (com libass, libfreetype e libx264).

```bash
pip install -e ".[dev]"
```

```bash
pip install faster-whisper   # transcrição automática (opcional, recomendado)
```

## Uso com o agente

1. Coloque o vídeo em `raw/` (ex.: `raw/podcast_ep12.mp4`).
2. Coloque logo, molduras, CTAs, músicas em `assets/overlays/` e `assets/music/` e descreva o uso no `docs/GUIA_DE_EDICAO.md` (seção 7).
3. Peça ao Claude Code: *"Use o clipador-editor para tirar 5 shorts do raw/podcast_ep12.mp4"*.

## Uso manual

```bash
python -m clipador analyze raw/video.mp4 -o projects/video/work/analysis.json
python -m clipador sheet raw/video.mp4 --every 30 -o projects/video/work/overview.jpg
python -m clipador transcribe raw/video.mp4 -o projects/video/work/transcript.json
python -m clipador transcript projects/video/work/transcript.json
python -m clipador render projects/exemplo/specs/01_exemplo_shorts.json --draft --preview
python -m clipador presets
```

## Documentação
- [Receita JSON — referência de campos](docs/RECEITA.md)
- [Guia de edição — padrões de estilo](docs/GUIA_DE_EDICAO.md)
- [Agente editor](.claude/agents/clipador-editor.md)
