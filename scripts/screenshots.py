"""Screenshots headless das telas. Uso: python scripts/screenshots.py [project_id]"""
import sys
from playwright.sync_api import sync_playwright
import os
B = os.environ.get("WISER_URL", "http://127.0.0.1:8765")
pid = sys.argv[1] if len(sys.argv) > 1 else None
with sync_playwright() as p:
    br = p.chromium.launch()
    for vw, tag in ((1280, "desktop"), (390, "celular")):
        pg = br.new_page(viewport={"width": vw, "height": 900})
        pg.goto(B + "/"); pg.wait_for_selector("h1"); pg.screenshot(path=f"screenshots/{tag}-0-inicio.png", full_page=True)
        pg.goto(B + "/#/novo"); pg.wait_for_selector("#f"); pg.screenshot(path=f"screenshots/{tag}-1-carregar.png", full_page=True)
        if pid:
            for n, name in ((1, "estrutura"), (2, "idiomas"), (3, "estilo"), (4, "revisar"), (5, "exportar")):
                pg.goto(f"{B}/#/p/{pid}/{n}"); pg.wait_for_timeout(1500)
                pg.screenshot(path=f"screenshots/{tag}-{n}-{name}.png", full_page=(n != 4))
        pg.close()
    br.close()
