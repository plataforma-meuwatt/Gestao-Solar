"""Modelos do BFF.

Só existe aqui o que NÃO existe nos upstreams: a identidade do usuário no Gestão Solar, o
vínculo entre a usina do meuWatt e a do meuPlano, e as assinaturas/mensalidades. Geração,
equipamentos, cronograma e OS não são replicados — vêm por API, sempre.
"""

from app.models.billing import Invoice, Subscription
from app.models.integracao import EstadoTeste, Integracao, Produto
from app.models.plant import PlantLink
from app.models.user import User, UserPlantAccess

__all__ = [
    "User",
    "UserPlantAccess",
    "PlantLink",
    "Subscription",
    "Invoice",
    "Integracao",
    "Produto",
    "EstadoTeste",
]
