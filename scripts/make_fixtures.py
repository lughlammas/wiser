"""Gera os arquivos de teste SINTÉTICOS de tests/fixtures (conteúdo inventado, sem manuscrito real).
Requer fpdf2 só para gerar o PDF (não é dependência do app)."""
from pathlib import Path
import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

F = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
F.mkdir(parents=True, exist_ok=True)
HEADER = "CADERNO SINTÉTICO DE TESTE"

# PDF de 3 páginas com cabeçalho repetido, títulos numerados, lista e referências
from fpdf import FPDF
pdf = FPDF(); pdf.add_font("dv", "", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
pages = [
    ["Guia de jardinagem", "", "1. Como preparar o solo",
     "O solo deve ser revolvido antes do plantio. A terra fica mais leve e as raízes crescem melhor.", "",
     "2. Ferramentas básicas", "1. Pá - para cavar e mover a terra.", "2. Regador - para molhar as mudas com cuidado."],
    ["3. Quando regar", "Regue de manhã cedo ou no fim da tarde, quando o sol está mais fraco.", "",
     "Nota: as quantidades variam conforme o clima da região."],
    ["Referências", "Silva, A. Manual da horta. Editora Exemplo, 2020. https://exemplo.org/horta"],
]
for lines in pages:
    pdf.add_page(); pdf.set_font("dv", size=11)
    pdf.cell(0, 8, HEADER, new_x="LMARGIN", new_y="NEXT")
    for l in lines:
        pdf.multi_cell(0, 7, l or " ", new_x="LMARGIN", new_y="NEXT")
pdf.output(str(F / "sintetico.pdf"))

# DOCX com listas numeradas/marcadores, tabela, nota de rodapé e caixa de texto
d = docx.Document()
d.add_heading("Receitas de teste", 0)
d.add_heading("Ingredientes", 1)
for t in ("farinha", "água", "sal"):
    d.add_paragraph(t, style="List Bullet")
d.add_heading("Passos", 1)
for t in ("Misture tudo.", "Descanse por uma hora.", "Asse por trinta minutos."):
    d.add_paragraph(t, style="List Number")
p = d.add_paragraph("Texto com nota de rodapé.")
ref = OxmlElement("w:footnoteReference"); ref.set(qn("w:id"), "1")
r = OxmlElement("w:r"); r.append(ref); p._p.append(r)
tb = d.add_table(rows=2, cols=2); tb.cell(0, 0).text = "Item"; tb.cell(0, 1).text = "Quantidade"
d.add_paragraph("Uma citação inventada.", style="Quote")
d.save(F / "sintetico.docx")
(F / "sintetico.md").write_text("# Título\n\n## Cap 1\n\nTexto.\n\n- item\n1. um\n\n> citação\n\n[^1]: nota\n\n## Referências\n\nAutor, Livro.\n", "utf-8")
(F / "sintetico.txt").write_text("1. Letras\n\nA letra Aleph (א) aparece no exemplo, ver https://exemplo.org/a.\n", "utf-8")
print("ok", sorted(x.name for x in F.iterdir()))
