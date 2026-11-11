"""Publicação automática.

YouTube (Shorts e vídeos longos): YouTube Data API v3, upload resumível, agendamento com publishAt.
  Configuração única (veja docs/PUBLICACAO.md):
    1. Google Cloud Console -> criar projeto -> ativar "YouTube Data API v3"
    2. Tela de consentimento OAuth + credencial "App para computador" -> baixar como secrets/youtube_client.json
    3. `python -m clipador publish-auth youtube` (abre o navegador uma vez; token fica em secrets/youtube_token.json)

TikTok e Instagram: as APIs oficiais exigem app aprovado (TikTok Content Posting API) ou conta
profissional + vídeo hospedado em URL pública (Instagram Graph API). Até lá, o pacote de entrega
(`package`) deixa tudo pronto para postar/agendar pelo celular ou pelo TikTok Studio / Meta Business Suite.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .deliver import post_text
from .ff import ClipadorError, probe
from .spec import load_spec, resolve_path
from .workspace import ROOT

SECRETS = ROOT / "secrets"
YT_CLIENT = SECRETS / "youtube_client.json"
YT_TOKEN = SECRETS / "youtube_token.json"
YT_SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]
LOG = ROOT / "out" / "publicados.jsonl"


def _yt_libs():
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
        from googleapiclient.http import MediaFileUpload  # type: ignore
    except ImportError as e:
        raise ClipadorError('publicação no YouTube precisa de: pip install -e ".[publicar]"') from e
    return Request, Credentials, InstalledAppFlow, build, MediaFileUpload


def youtube_auth(headless: bool = False):
    Request, Credentials, InstalledAppFlow, build, _ = _yt_libs()
    creds = None
    if YT_TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(YT_TOKEN), YT_SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not YT_CLIENT.exists():
            raise ClipadorError(f"faltou {YT_CLIENT} (credencial OAuth 'App para computador' do Google Cloud)")
        flow = InstalledAppFlow.from_client_secrets_file(str(YT_CLIENT), YT_SCOPES)
        creds = flow.run_local_server(port=0, open_browser=not headless)
    SECRETS.mkdir(exist_ok=True)
    YT_TOKEN.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def youtube_payload(spec: dict, privacy: str = "private", publish_at: str | None = None,
                    category: str = "20") -> dict:
    """Corpo do upload. category 20 = Gaming."""
    video = resolve_path(spec, spec["output"])
    info = probe(video)
    is_short = info["height"] > info["width"] and info["duration"] <= 180
    pt = post_text(spec, "shorts" if is_short else "youtube")
    title = pt["title"]
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if publish_at:
        # agendamento: o vídeo precisa subir como private e o YouTube publica na hora marcada
        datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
        status.update(privacyStatus="private", publishAt=publish_at)
    return {"snippet": {"title": title, "description": pt["description"][:5000], "tags": pt["tags"][:30],
                        "categoryId": category, "defaultLanguage": "pt-BR", "defaultAudioLanguage": "pt-BR"},
            "status": status, "_video": video, "_short": is_short}


def youtube_upload(spec_path: str, privacy: str = "private", publish_at: str | None = None,
                   thumbnail: str | None = None, dry_run: bool = False, progress=None) -> dict:
    spec = load_spec(spec_path)
    body = youtube_payload(spec, privacy, publish_at)
    video = body.pop("_video")
    short = body.pop("_short")
    if dry_run:
        return {"dry_run": True, "video": video, "short": short, "body": body}
    _, _, _, _, MediaFileUpload = _yt_libs()
    yt = youtube_auth(headless=True)
    media = MediaFileUpload(video, chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        st, resp = req.next_chunk()
        if st and progress:
            progress(st.progress())
    vid = resp["id"]
    if thumbnail and Path(thumbnail).exists() and not short:
        yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(thumbnail)).execute()
    rec = {"platform": "youtube", "id": vid, "url": f"https://youtu.be/{vid}", "spec": spec_path,
           "privacy": body["status"]["privacyStatus"], "publish_at": publish_at, "at": datetime.now().isoformat()}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec
