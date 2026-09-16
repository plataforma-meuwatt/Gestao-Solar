"""Gateway de WhatsApp do Gestão Solar.

O pacote NÃO se chama `app`, e isso é deliberado: com o `PYTHONPATH` do BFF exportado, dois
pacotes `app` na mesma máquina se atropelam, e o erro chega disfarçado de "cannot import
name". A lição veio do Talk Solar.
"""
