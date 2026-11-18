"""A imagem da API instala o Playwright numa camada antes do requirements.txt (o Chromium da foto do mapa): as duas
versões têm de ser a mesma, senão o pacote procura um navegador que a imagem não tem e a foto nunca sai."""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def test_playwright_do_dockerfile_e_o_do_requirements():
    docker = re.search(r"playwright==([\d.]+)", (RAIZ / "Dockerfile").read_text())
    req = re.search(r"^playwright==([\d.]+)", (RAIZ / "requirements.txt").read_text(), re.M)
    assert docker and req and docker.group(1) == req.group(1)
