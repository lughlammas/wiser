# WISER — fábrica editorial de adaptações

Site local para adaptar manuscritos a outro idioma: **carregar → idiomas → estilo → revisar → exportar**.
Interface em português do Brasil, sem CDN, servidor em `127.0.0.1`.

## Instalação

```bash
cd /workspace/wiser
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt            # versões fixas
# opcional: .venv/bin/pip install -r requirements-optional.txt   (argos, playwright)
cp .env.example .env    # edite e escolha o provedor
.venv/bin/python -m wiser.app      # http://127.0.0.1:8765
```

## Provedor de IA (camada de serviço no servidor)

Definido **só** por `WISER_PROVIDER` no `.env` (ou ambiente). Não há troca automática entre provedores:
se o escolhido falhar, a tela explica o motivo e nada é simulado.

| `WISER_PROVIDER` | O que é | Configuração | Privacidade |
|---|---|---|---|
| `ollama` | modelo local via API compatível OpenAI | `ollama serve`; `WISER_MODEL` (padrão `qwen2.5:1.5b`); `WISER_OLLAMA_URL` (padrão `http://localhost:11434/v1`). Só aparece como disponível se o servidor responder e o modelo existir. | texto não sai da máquina |
| `gemini` | Google Gemini API | `GEMINI_API_KEY` (só no servidor), `WISER_MODEL` (padrão `gemini-flash-latest`) | texto vai ao Google; na faixa grátis pode ser usado para melhorar produtos |
| `argos` | Argos Translate (NMT local) | `.venv/bin/python -m wiser.setup_argos pt en` | local; tradução direta, **não** aplica estilo/tom |

Mensagens tratadas: chave ausente/recusada, serviço indisponível, limite de uso (429), erro de geração
(ex.: modelo não devolveu todos os trechos). O progresso é salvo por parte; "Continuar adaptação" retoma
do ponto onde parou.

Manuscritos longos são divididos em partes (`WISER_CHUNK_CHARS`, padrão 900) sem quebrar blocos; cada bloco
tem id e tipo, e a resposta é remontada na ordem original. URLs e escrita hebraica/árabe são protegidas;
o glossário vai junto em cada parte e, nos LLMs, é conferido depois (termo ausente vira sinalização).

## Recursos

- Entrada: texto colado, DOCX, PDF, MD, TXT (até 20 MB). Avisos para imagens, tabelas, notas de rodapé
  e caixas de texto não importadas, PDF protegido/escaneado, cabeçalhos repetidos removidos, escrita RTL.
- Estrutura detectada: títulos/capítulos/subtítulos, parágrafos, listas, citações, notas, referências.
- Estilos: fiel ao original, natural no idioma de destino (padrão), adaptado ao público local; público,
  região, tom e termos fixos opcionais.
- Revisão lado a lado por seção, edição com salvamento automático, sinalizações com botão "Decidido".
- Glossário por projeto (com sugestão de nomes recorrentes — só sugestão).
- Projetos salvos em `data/projects/<id>/` (pasta 0700; cópia somente-leitura do original). Exportações em
  `data/projects/<id>/exports/`. `data/` não é versionado.
- Exportação DOCX e Markdown apenas quando todos os trechos estão adaptados.

## Revisão e exportação (etapa 2)

- Depois de adaptar, cada trecho passa por uma checagem de **resíduo do idioma de origem** (listas de
  palavras funcionais por idioma: pt, en, es, fr, de, it, pl). Nomes próprios, URLs, trechos entre aspas
  (citações preservadas), referências bibliográficas, `código` e escrita hebraica/árabe são ignorados.
  Detecção inconclusiva (par sem lista, mistura, trecho idêntico curto) vira **“revisão necessária”**.
  Nenhum trecho é aprovado automaticamente. A checagem é refeita a cada edição.
- Severidades: **Informativo** (sem ação), **Decisão editorial** (aviso) e **Bloqueador**
  (resíduo de origem, conteúdo protegido perdido).
- Exportar: bloqueado se faltar trecho ou houver bloqueador aberto (corrija o texto ou registre a decisão
  por escrito). Com avisos abertos, a tela lista cada um e exige marcar a confirmação (`?confirm=true` na API).
- Excluir projeto: botão “Excluir” na tela inicial, com confirmação digitando o nome. Apaga
  `data/projects/<id>/` inteiro (dados, cópia do original, exportações). Nada é enviado a serviço algum.
- DOCX: numeração (decimal, letras, romanos) e marcadores são lidos do `numbering.xml` e mantidos como
  marcador literal; a exportação reaplica o marcador do original mesmo se o modelo o perder. Tabelas, notas
  de rodapé/fim, caixas de texto, imagens, comentários, equações e cabeçalhos/rodapés são **listados como
  não importados** na etapa 1 (não são preservados).

## Testes

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/screenshots.py <id>   # servidor rodando (WISER_URL); gera screenshots/
.venv/bin/python scripts/make_fixtures.py      # regenera tests/fixtures (conteúdo sintético; requer fpdf2)
```

Os testes usam apenas arquivos sintéticos de `tests/fixtures/` e caminhos relativos. Screenshots usam só
conteúdo sintético.

## Licença

Ainda não definida pelo proprietário (sem arquivo LICENSE).

```text
```
