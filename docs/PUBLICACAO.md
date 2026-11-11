# Entrega e publicação

## Fluxo de trabalho

```
seu amigo faz a live
   → você me passa o VOD (+ chat, se tiver)
   → eu rodo: scan → escolho os momentos → receitas com gancho/título/legenda → render
   → pacote em entregas/<data>/ (vídeo + thumbnail + textos por plataforma)
   → publicação: YouTube automática (agendada) · TikTok/Reels pelo pacote
```

## Pacote de entrega

`python -m clipador package projects/<vod>/specs/*.json` (ou o botão **📦 Pacote de entrega** na interface) cria:

```
entregas/2026-11-20/
  c01_shorts/          c01_shorts.mp4 · thumbnail.jpg · post.md · post.json
  compilacao_youtube/  compilacao_youtube.mp4 · thumbnail.jpg · post.md (com capítulos)
  index.json
```

`post.md` traz título, descrição/legenda e hashtags prontos para cada plataforma (Shorts, TikTok, Reels, YouTube). Os textos vêm do campo `post` da receita:

```json
"post": {
  "title": "Ele achou que ia dar certo… 😂",
  "description": "Clipe da live de GTA.",
  "hashtags": ["#gta6", "#gta"],
  "credit": "🎮 Live: twitch.tv/nome_do_canal",
  "thumb_text": "NÃO ACREDITO",
  "thumbnail": {"time": 312.5, "text": "...", "face_rect": [0.02, 0.52, 0.27, 0.37]},
  "platforms": {"tiktok": {"title": "...", "hashtags": ["#fyp"]}},
  "chapters": ["00:00 A fuga", "01:12 O helicóptero"]
}
```

## YouTube — publicação automática (Shorts e longos)

Configuração única, feita por você (a conta é sua, a senha nunca passa por mim):

1. Em https://console.cloud.google.com crie um projeto e ative a **YouTube Data API v3**.
2. Em *APIs e serviços → Tela de consentimento OAuth*: tipo **Externo**, adicione seu e-mail como usuário de teste.
3. Em *Credenciais → Criar credencial → ID do cliente OAuth → App para computador*. Baixe o JSON e salve como `secrets/youtube_client.json` (a pasta `secrets/` está fora do git).
4. Instale e autorize (abre o navegador uma vez):

   ```bash
   pip install -e ".[publicar]"
   ```

   ```bash
   python -m clipador publish-auth youtube
   ```

Depois disso:

```bash
python -m clipador publish projects/<vod>/specs/c01_shorts.json --publish-at 2026-11-20T18:00:00-03:00
```

- Sem `--publish-at` o vídeo sobe **privado** (padrão seguro, para revisão). Com `--publish-at` sobe privado e o YouTube publica na hora marcada.
- Vertical de até 3 min vira Short automaticamente (`#shorts` é adicionado).
- Thumbnail personalizada é enviada para vídeos longos (exige conta verificada no YouTube).
- Cada envio fica registrado em `out/publicados.jsonl`.
- Cota padrão da API: ~6 uploads por dia por projeto (10.000 unidades; upload = 1.600). Para mais, peça aumento de cota no Google Cloud.
- **Importante:** projetos novos da API que ainda não passaram pela auditoria do YouTube (*YouTube API Services – Audit and Quota Extension*, formulário gratuito) têm todos os uploads travados como **privados**, inclusive os agendados. Até a auditoria ser aprovada, o fluxo é: a ferramenta sobe privado com título/descrição/tags prontos, e você só muda para público ou agenda no YouTube Studio (1 clique por vídeo).

## TikTok e Instagram Reels

As APIs oficiais exigem:
- **TikTok**: app registrado no TikTok for Developers com a *Content Posting API*; até a auditoria ser aprovada, os posts via API ficam só visíveis para você.
- **Instagram**: conta Profissional ligada a uma Página do Facebook + app na Meta com permissão `instagram_content_publish`; o vídeo precisa estar numa URL pública.

Enquanto isso, o caminho prático é usar o pacote: abrir o `post.md` no celular, copiar a legenda e postar/agendar pelo app, pelo **TikTok Studio** (agenda até 10 dias) e pelo **Meta Business Suite** (agenda Reels no Instagram e Facebook). Quando as contas/app estiverem aprovados, dá para adicionar a publicação automática nessas plataformas no mesmo `clipador/publish.py`.

## Cadência sugerida para começar

- 2–3 Shorts/Reels/TikToks por dia (os melhores candidatos de cada live).
- 1 vídeo longo por semana: “melhores momentos da semana” (`compile` com 10–15 momentos).
- Postar o mesmo corte nas três plataformas, com texto adaptado.
