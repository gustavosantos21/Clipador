# Clipador

Ferramenta de clipagem e edição de vídeo (YouTube, Shorts, Reels, TikTok) operada por um agente. O agente lê o bruto, decide os cortes e descreve cada vídeo final numa **receita JSON**; o motor (`clipador/`, Python + ffmpeg) renderiza.

- Edição de vídeo → use o agente `clipador-editor` (`.claude/agents/clipador-editor.md`).
- Padrões de edição: `docs/GUIA_DE_EDICAO.md`. Formato da receita: `docs/RECEITA.md`.
- CLI: `python -m clipador --help`. Testes: `python -m pytest -q` (geram mídia sintética, ~10 s).

## Pastas
- `raw/` material bruto (fora do git) · `out/` vídeos renderizados (fora do git)
- `projects/<nome>/` receitas (`specs/`), `CORTES.md`, `work/` (transcrição, análise; fora do git)
- `assets/overlays|fonts|music` arquivos da marca · `styles/captions/` estilos de legenda

## Código
- `ff.py` tempo/probe/ffmpeg/fontes · `analyze.py` silêncio, cenas, energia, folha de contato
- `transcript.py` faster-whisper/SRT · `captions.py` legendas .ass animadas
- `faces.py` detecção de rosto (YuNet/Haar), recorte automático, facecam · `highlights.py` scan de stream (áudio+chat)
- `jobs.py` fila SQLite + workers · `server.py` + `web/index.html` interface local (`python -m clipador serve`) · `workspace.py` pastas e receitas automáticas
- `spec.py` validação e expansão da receita (jump cuts, mapa origem→saída) · `render.py` monta o filtergraph único
- Ao adicionar um campo na receita: implementar em `render.py`/`spec.py`, documentar em `docs/RECEITA.md`, cobrir em `tests/`.
