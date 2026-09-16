"""Importar os modelos aqui é o que registra as tabelas no metadata.

Sem isto o `alembic revision --autogenerate` não vê tabela nenhuma e gera uma migration
vazia — falha que não dá erro, só um arquivo inútil que alguém aplica achando que fez algo.
"""

from gateway.models.credencial import Credencial, CredencialEvento
from gateway.models.mensagem import Mensagem, WebhookEvento

__all__ = ["Credencial", "CredencialEvento", "Mensagem", "WebhookEvento"]
