#!/usr/bin/env python3
"""
atualizar.py — one-click project updater, no git required.

Downloads the newest code from the public GitHub repo as a ZIP, extracts it,
and overlays the code over this folder. Your personal data (drg_stats.db,
*.sav, watcher.log, screenshots) is NEVER inside the repo ZIP, so it's left
untouched automatically — the overlay only ever writes tracked project files.

Pure standard library (urllib + zipfile): works whether the project was cloned
with git OR downloaded as a ZIP — no git, no pip. Double-click atualizar.bat,
or run:  python atualizar.py

This module is also imported by dashboard.py, which reuses sha_remota() /
versao_local() / gravar_marcador() to power the "update available" notice
WITHOUT git.
"""
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = "gilas-byte/DRG-Stats-Tracker"
BRANCH = "main"
ZIP_URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"
SHA_URL = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
PROJETO = Path(__file__).resolve().parent
# Local-only marker (gitignored): the commit SHA this copy is synced to. The
# dashboard compares it with the branch's latest SHA to decide if an update
# exists. It's not in the repo ZIP, so updating never overwrites it wrongly.
MARCADOR = PROJETO / ".update_check"
_UA = {"User-Agent": "DRG-Stats-Tracker-updater"}


def sha_remota(timeout: int = 15) -> str | None:
    """The branch's latest commit SHA, via the GitHub API. None on any failure.

    The `Accept: application/vnd.github.sha` media type makes the API return the
    bare SHA string (no JSON to parse). Works unauthenticated on public repos.
    """
    try:
        req = urllib.request.Request(
            SHA_URL, headers={**_UA, "Accept": "application/vnd.github.sha"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode().strip() or None
    except Exception:
        return None


def versao_local() -> str | None:
    """The SHA this copy was last synced to (from the marker file), or None."""
    try:
        return MARCADOR.read_text(encoding="utf-8").strip() or None
    except Exception:
        return None


def gravar_marcador(sha: str) -> None:
    """Record the SHA we're now synced to (best-effort; ignores write errors)."""
    try:
        MARCADOR.write_text(sha, encoding="utf-8")
    except Exception:
        pass


def _baixar_zip(timeout: int = 60) -> bytes:
    req = urllib.request.Request(ZIP_URL, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _aplicar(zip_bytes: bytes) -> tuple[int, int]:
    """Overlay the ZIP's files onto the project. Returns (updated, added).

    The archive's top folder is like "DRG-Stats-Tracker-main/"; we strip it and
    write each file to the matching path under the project. We never delete —
    only write/overwrite — so a file that exists locally but not in the archive
    (your database, saves, etc.) is left alone.
    """
    atualizados = adicionados = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        nomes = z.namelist()
        raiz = nomes[0].split("/", 1)[0] + "/"      # e.g. "DRG-Stats-Tracker-main/"
        for nome in nomes:
            if nome.endswith("/"):
                continue                            # skip directory entries
            rel = nome[len(raiz):] if nome.startswith(raiz) else nome
            if not rel:
                continue
            destino = PROJETO / rel
            existia = destino.exists()
            destino.parent.mkdir(parents=True, exist_ok=True)
            with z.open(nome) as src, open(destino, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if existia:
                atualizados += 1
            else:
                adicionados += 1
    return atualizados, adicionados


def main() -> int:
    print()
    print("   ============================================")
    print("      DRG Stats Tracker - Atualizar")
    print("   ============================================")
    print()
    print("   Baixando a versao mais nova do GitHub...")
    try:
        zip_bytes = _baixar_zip()
    except Exception as e:
        print("   [ERRO] Nao consegui baixar. Verifique sua internet.")
        print(f"          (detalhe: {e})")
        return 1
    try:
        atualizados, adicionados = _aplicar(zip_bytes)
    except Exception as e:
        print("   [ERRO] Baixei, mas falhei ao gravar os arquivos.")
        print(f"          (detalhe: {e})")
        return 1
    sha = sha_remota()
    if sha:
        gravar_marcador(sha)
    print()
    print(f"   Pronto! {atualizados} arquivo(s) atualizado(s), {adicionados} novo(s).")
    print("   Seus dados (historico, saves, log) nao foram tocados.")
    print("   (Se o painel estava aberto, feche e abra de novo.)")
    return 0


if __name__ == "__main__":
    codigo = main()
    print()
    try:
        input("   Pressione Enter para fechar...")
    except EOFError:
        pass
    sys.exit(codigo)
