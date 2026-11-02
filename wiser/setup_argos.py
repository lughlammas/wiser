"""Instala um par de idiomas do Argos Translate (gratuito). Uso: python -m wiser.setup_argos pt en"""
import sys
import argostranslate.package as p

src, tgt = sys.argv[1], sys.argv[2]
p.update_package_index()
pk = [x for x in p.get_available_packages() if x.from_code == src and x.to_code == tgt]
if not pk:
    sys.exit(f"Par {src}->{tgt} não disponível no índice do Argos.")
p.install_from_path(pk[0].download())
print(f"Instalado: {src} -> {tgt}")
