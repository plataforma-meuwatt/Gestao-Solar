# -*- coding: utf-8 -*-
"""Onde os anexos ficam.

Dois destinos com a MESMA interface: disco (para desenvolver) e Supabase Storage (o projeto do
Gestão Solar). Quem chama não sabe qual está em uso — e é isso que permite trocar sem mexer no
resto.

⚠ `TALK_STORAGE=local` no Railway significa **perder os anexos a cada deploy** (o disco do
contêiner é efêmero). O servidor avisa isso em `/saude`, alto, porque é o tipo de detalhe que
só se descobre quando a foto de três semanas atrás não abre mais.
"""
from __future__ import annotations

import io
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Optional

import httpx

from . import config

TIPOS_OK = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "application/pdf", "text/plain", "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel", "application/msword", "application/zip",
}


def validar(tipo: str, tamanho: int) -> Optional[str]:
    """A recusa acontece ANTES de gravar o primeiro byte — nada de arquivo órfão."""
    if tipo not in TIPOS_OK:
        return f"tipo não suportado ({tipo})"
    if tamanho > config.MAX_ARQUIVO_MB * 1024 * 1024:
        return f"arquivo maior que {config.MAX_ARQUIVO_MB} MB"
    if tamanho <= 0:
        return "arquivo vazio"
    return None


def _ext(nome: str, tipo: str) -> str:
    e = Path(nome or "").suffix
    return e if e else (mimetypes.guess_extension(tipo or "") or ".bin")


def _gravar(chave: str, dados: bytes, tipo: str) -> None:
    if config.STORAGE == "supabase":
        r = httpx.post(
            f"{config.SUPABASE_URL}/storage/v1/object/{config.SUPABASE_BUCKET}/{chave}",
            content=dados, timeout=60,
            headers={"Authorization": f"Bearer {config.SUPABASE_KEY}",
                     "Content-Type": tipo or "application/octet-stream",
                     "x-upsert": "true"})
        r.raise_for_status()
        return
    destino = Path(config.STORAGE_DIR) / chave
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(dados)


def url(chave: Optional[str], base: str = "") -> Optional[str]:
    """A URL que a TELA usa.

    Assinada e temporária no Supabase; caminho local em desenvolvimento. Resolvida no servidor
    de propósito: uma tag `<img>` não leva cabeçalho de autenticação, então uma rota da API no
    `src` apareceria quebrada.
    """
    if not chave:
        return None
    if config.STORAGE == "supabase":
        try:
            r = httpx.post(
                f"{config.SUPABASE_URL}/storage/v1/object/sign/{config.SUPABASE_BUCKET}/{chave}",
                json={"expiresIn": 3600}, timeout=20,
                headers={"Authorization": f"Bearer {config.SUPABASE_KEY}"})
            if r.status_code < 300:
                return f"{config.SUPABASE_URL}/storage/v1{r.json()['signedURL']}"
        except (httpx.RequestError, KeyError, ValueError):
            return None
        return None
    return f"{base.rstrip('/')}/arquivos/{chave}"


def apagar(chave: Optional[str]) -> None:
    if not chave:
        return
    if config.STORAGE == "supabase":
        try:
            httpx.request(
                "DELETE",
                f"{config.SUPABASE_URL}/storage/v1/object/{config.SUPABASE_BUCKET}/{chave}",
                timeout=20, headers={"Authorization": f"Bearer {config.SUPABASE_KEY}"})
        except httpx.RequestError:
            pass
    else:
        try:
            os.remove(Path(config.STORAGE_DIR) / chave)
        except OSError:
            pass


def miniatura(dados: bytes, tipo: str) -> tuple[Optional[bytes], Optional[int], Optional[int]]:
    """`(miniatura, largura, altura)` de uma imagem.

    A miniatura é o que permite a foto aparecer NA CONVERSA: rolar dez mensagens baixando dez
    arquivos de 4 MB trava a tela, e quem usa conclui que o programa é ruim — não que a foto é
    grande. Largura e altura evitam o texto abaixo saltar enquanto a imagem carrega.

    Falhar aqui não impede o anexo: imagem exótica ou corrompida entra sem miniatura.
    """
    if not (tipo or "").startswith("image/"):
        return None, None, None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(dados)) as im:
            larg, alt = im.size
            im.thumbnail((520, 520))
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="JPEG", quality=82)
            return buf.getvalue(), larg, alt
    except Exception:                       # noqa: BLE001
        return None, None, None


def guardar(canal_id: int, dados: bytes, nome: str, tipo: str) -> dict:
    """Grava o anexo (e a miniatura, se for imagem). Devolve o que vai para o banco."""
    fid = uuid.uuid4().hex
    chave = f"canais/{canal_id}/{fid}{_ext(nome, tipo)}"
    _gravar(chave, dados, tipo)
    thumb, larg, alt = miniatura(dados, tipo)
    chave_thumb = None
    if thumb:
        chave_thumb = f"canais/{canal_id}/thumbs/{fid}.jpg"
        _gravar(chave_thumb, thumb, "image/jpeg")
    return {"caminho": chave, "thumb_caminho": chave_thumb, "bytes": len(dados),
            "largura": larg, "altura": alt}
