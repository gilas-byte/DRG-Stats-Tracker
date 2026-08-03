#!/usr/bin/env python3
"""
renomeador.py — fica vigiando uma pasta e renomeia imagens novas pra 1, 2, 3, 4...

Sempre que uma imagem nova cai na pasta, ela ganha o próximo número da fila.
Imagens que JÁ têm nome de número (ex: "7.png") são ignoradas — senão o script
ficaria renomeando elas pra sempre num loop infinito.

Uso:
    python renomeador.py                 # usa a PASTA configurada abaixo
    python renomeador.py "/caminho/pasta" # ou passa a pasta como argumento
"""

import sys
import time
from pathlib import Path

# ------------------------------- configuração -------------------------------
# MUDE AQUI pro caminho da sua pasta (ou passe como argumento na linha de comando).
# Windows exemplo:  Path(r"C:\Users\gilas\Pictures\entrada")
# Linux exemplo:    Path("/home/gilas/imagens/entrada")
PASTA = Path.home() / "C:/Users/Usuario/Desktop/arquivos/codigos/Papaio-Stats/enemies_screenshot"

EXTENSOES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}
INTERVALO = 1          # segundos entre cada verificação da pasta
# ----------------------------------------------------------------------------


def proximo_numero(pasta: Path) -> int:
    """Descobre o próximo número livre olhando os arquivos já numerados.

    Fazemos isso a cada rodada (em vez de guardar um contador em memória) pra
    que o script possa ser fechado e reaberto sem perder a conta.
    """
    usados = [int(p.stem) for p in pasta.iterdir()
              if p.is_file() and p.stem.isdigit()]
    return max(usados, default=0) + 1


def arquivo_estavel(caminho: Path, tentativas: int = 2, espera: float = 0.5) -> bool:
    """Retorna True só quando o tamanho do arquivo para de mudar.

    ARMADILHA CLÁSSICA: quando você copia/arrasta uma imagem grande pra pasta,
    o arquivo APARECE antes de terminar de ser escrito. Se o script agarrar ele
    no meio da cópia, você renomeia um arquivo pela metade (corrompido). Então a
    gente espera o tamanho ficar estável antes de mexer.
    """
    try:
        anterior = caminho.stat().st_size
    except OSError:
        return False
    for _ in range(tentativas):
        time.sleep(espera)
        try:
            atual = caminho.stat().st_size
        except OSError:
            return False
        if atual != anterior:
            return False
        anterior = atual
    return True


def imagens_novas(pasta: Path):
    """Imagens cujo nome ainda NÃO é um número puro, das mais antigas pras novas.

    Ordenar por data de modificação garante que quem chegou primeiro pega o
    número menor — a fila fica justa.
    """
    novas = [p for p in pasta.iterdir()
             if p.is_file()
             and p.suffix.lower() in EXTENSOES
             and not p.stem.isdigit()]
    return sorted(novas, key=lambda p: p.stat().st_mtime)


def processar(pasta: Path) -> int:
    """Renomeia todas as imagens novas que estiverem prontas. Retorna quantas."""
    renomeadas = 0
    for img in imagens_novas(pasta):
        if not arquivo_estavel(img):
            continue  # ainda copiando; deixa pra próxima volta

        n = proximo_numero(pasta)
        destino = pasta / f"{n}{img.suffix.lower()}"
        while destino.exists():           # segurança extra contra colisão
            n += 1
            destino = pasta / f"{n}{img.suffix.lower()}"

        try:
            img.rename(destino)
            print(f"  {img.name}  ->  {destino.name}")
            renomeadas += 1
        except OSError as e:
            print(f"  [erro] {img.name}: {e}")
    return renomeadas


def main():
    pasta = Path(sys.argv[1]) if len(sys.argv) > 1 else PASTA
    if not pasta.is_dir():
        print(f"Pasta não encontrada: {pasta}")
        print("Edite a variável PASTA no topo do script ou passe o caminho como argumento.")
        sys.exit(1)

    print(f"Vigiando: {pasta}   (Ctrl+C pra parar)")
    try:
        while True:
            processar(pasta)
            time.sleep(INTERVALO)
    except KeyboardInterrupt:
        print("\nParado. Rock and Stone!")


if __name__ == "__main__":
    main()