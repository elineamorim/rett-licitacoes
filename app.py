from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import requests
from urllib.parse import unquote, quote
from concurrent.futures import ThreadPoolExecutor
import fitz
import base64
import re
from html import escape

app = FastAPI()
BASE_URL = "https://pncp.gov.br/api/search/"

MODALIDADES = {
    "Pregão - Eletrônico": "6",
    "Concorrência - Eletrônica": "4",
    "Dispensa": "8",
    "Credenciamento": "12",
    "Leilão": "5",
}

UFS = ["AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"]


def normalizar_texto_busca(texto):
    texto = str(texto or "").lower()
    trocas = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u",
        "ç": "c",
    }
    for a, b in trocas.items():
        texto = texto.replace(a, b)
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def palavra_exata_no_objeto(objeto, termo):
    """
    Filtra o resultado pelo OBJETO da licitação.
    Evita falso positivo do PNCP, como pesquisar 'motorista' e aparecer ar-condicionado.
    """
    termo = normalizar_texto_busca(termo)
    objeto = normalizar_texto_busca(objeto)

    if not termo:
        return True

    sinonimos = {
        "motorista": [
            "motorista",
            "motoristas",
            "condutor",
            "condutores",
            "cnh b",
            "cnh d",
            "servico de motorista",
            "servicos de motorista",
            "mao de obra motorista",
        ],

        "veiculo": [
            "veiculo",
            "veiculos",
            "locacao de veiculos",
            "locacao de veiculo",
            "aluguel de veiculos",
            "aluguel de veiculo",
            "transporte terrestre",
            "pick up",
            "pickup",
            "van",
            "caminhonete",
        ],

        "veiculos": [
            "veiculo",
            "veiculos",
            "locacao de veiculos",
            "locacao de veiculo",
            "aluguel de veiculos",
            "aluguel de veiculo",
            "transporte terrestre",
            "pick up",
            "pickup",
            "van",
            "caminhonete",
        ],

        "limpeza": [
            "limpeza",
            "conservacao",
            "higienizacao",
            "asseio",
            "servicos de limpeza",
            "servico de limpeza",
        ],

        "medicamento": [
            "medicamento",
            "medicamentos",
            "farmaco",
            "farmacos",
            "insumo farmaceutico",
            "insumos farmaceuticos",
        ],

        "medicamentos": [
            "medicamento",
            "medicamentos",
            "farmaco",
            "farmacos",
            "insumo farmaceutico",
            "insumos farmaceuticos",
        ],

        "engenharia": [
            "engenharia",
            "obra",
            "obras",
            "reforma",
            "construcao",
            "manutencao predial",
            "servicos de engenharia",
            "servico de engenharia",
        ],

        "horas voo": [
            "horas voo",
            "hora voo",
            "transporte aereo",
            "helicoptero",
            "aeronave",
            "asa fixa",
            "asa rotativa",
        ],

        "hora voo": [
            "horas voo",
            "hora voo",
            "transporte aereo",
            "helicoptero",
            "aeronave",
            "asa fixa",
            "asa rotativa",
        ],
    }

    termos = sinonimos.get(termo, [termo])

    objeto_com_espaco = f" {objeto} "

    for palavra in termos:
        palavra = normalizar_texto_busca(palavra)
        if not palavra:
            continue

        # expressão exata/composta dentro do objeto
        if f" {palavra} " in objeto_com_espaco:
            return True

    return False




def montar_link(item_url):
    if not item_url:
        return "#"
    if item_url.startswith("/compras/"):
        return "https://pncp.gov.br/app/editais" + item_url.replace("/compras", "")
    if item_url.startswith("http"):
        return item_url
    return "https://pncp.gov.br" + item_url


def consultar_pncp(q="", pagina=1, uf="", modalidade_id="", tam=50):
    params = {
        "tipos_documento": "edital",
        "ordenacao": "-data",
        "pagina": pagina,
        "tam_pagina": tam,
        "status": "recebendo_proposta",
    }
    if q:
        params["q"] = q
    if uf:
        params["ufs"] = uf
    if modalidade_id:
        params["modalidades"] = modalidade_id

    r = requests.get(BASE_URL, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    return r.json()


@app.get("/buscar")
def buscar(q: str = "", pagina: int = 1, uf: str = "", modalidade: str = ""):
    try:
        modalidade_id = MODALIDADES.get(modalidade, "")
        dados = consultar_pncp(q=q, pagina=pagina, uf=uf, modalidade_id=modalidade_id, tam=100)

        itens = []
        for x in dados.get("items", []):
            objeto = (
                x.get("description", "")
                or x.get("title", "")
                or x.get("objetoCompra", "")
                or x.get("objeto", "")
            )

            # Filtro real por palavra-chave no OBJETO.
            # Se o usuário pesquisar "motorista", só entra resultado cujo objeto fale de motorista/condutor/CNH.
            if q and not palavra_exata_no_objeto(objeto, q):
                continue

            itens.append({
                "id": x.get("id", ""),
                "orgao": x.get("orgao_nome", "-"),
                "objeto": objeto,
                "uf": x.get("uf", "-"),
                "modalidade": x.get("modalidade_licitacao_nome", "-"),
                "inicio": x.get("data_inicio_vigencia", "-"),
                "fim": x.get("data_fim_vigencia", "-"),
                "valor": x.get("valor_global", "-"),
                "link": montar_link(x.get("item_url", ""))
            })

        def total_modalidade(par):
            nome, mid = par
            try:
                return nome, consultar_pncp(q=q, uf=uf, modalidade_id=mid, tam=1).get("total", 0)
            except Exception:
                return nome, 0

        def total_uf(estado):
            try:
                return estado, consultar_pncp(q=q, uf=estado, modalidade_id=modalidade_id, tam=1).get("total", 0)
            except Exception:
                return estado, 0

        with ThreadPoolExecutor(max_workers=8) as executor:
            modalidades = dict(executor.map(total_modalidade, MODALIDADES.items()))
            ufs = dict(executor.map(total_uf, UFS))

        return JSONResponse({
            "total_pncp": dados.get("total", 0),
            "pagina": pagina,
            "items": itens,
            "modalidades": modalidades,
            "ufs": ufs
        })

    except Exception as e:
        return JSONResponse({
            "total_pncp": 0,
            "pagina": pagina,
            "items": [],
            "modalidades": {},
            "ufs": {},
            "erro": str(e)
        })


def extrair_partes_link(link):
    try:
        partes = link.split("/app/editais/")[1].split("/")
        return partes[0], partes[1], partes[2]
    except Exception:
        return None, None, None


def url_arquivos_base(link):
    cnpj, ano, sequencial = extrair_partes_link(link)
    if not cnpj:
        return None
    return f"https://pncp.gov.br/pncp-api/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/arquivos"


def buscar_arquivos_licitacao(link):
    base = url_arquivos_base(link)
    if not base:
        return [], "Não foi possível montar URL dos arquivos."

    headers = {"User-Agent": "Mozilla/5.0"}
    todos = []

    for pagina in range(1, 6):
        url = f"{base}?pagina={pagina}&tamanhoPagina=20"
        try:
            r = requests.get(url, headers=headers, timeout=40)
            try:
                dados = r.json()
            except Exception:
                break

            if isinstance(dados, list):
                itens = dados
            elif isinstance(dados, dict):
                itens = dados.get("items") or dados.get("content") or []
            else:
                itens = []

            if not itens:
                break

            todos.extend(itens)

        except Exception:
            break

    if not todos:
        try:
            url = f"{base}/1"
            r = requests.get(url, headers=headers, timeout=40)
            if r.content.startswith(b"%PDF"):
                return [{
                    "nome": "Arquivo principal",
                    "tipo": "PDF",
                    "url": url,
                    "conteudo_direto": r.content
                }], ""
        except Exception:
            pass

    return todos, ""


def arquivo_eh_importante(arq):
    nome = str(arq.get("nome") or arq.get("titulo") or arq.get("name") or "").lower()
    tipo = str(arq.get("tipo") or arq.get("tipoDocumentoNome") or arq.get("tipo_documento_nome") or "").lower()
    texto = nome + " " + tipo

    palavras = [
        "edital",
        "termo de referência",
        "termo de referencia",
        "termo",
        "anexo",
        "aviso",
        "participação",
        "participacao",
        "habilitação",
        "habilitacao",
        "proposta",
        "modelo",
        "formulário",
        "formulario"
    ]

    ignorar = [
        "dfd",
        "estudo técnico preliminar",
        "estudo tecnico preliminar",
        "etp",
        "jornal",
        "publicação",
        "publicacao"
    ]

    if any(x in texto for x in ignorar) and not any(y in texto for y in ["edital", "termo", "anexo", "habilitação", "habilitacao"]):
        return False

    return any(p in texto for p in palavras)


def pegar_url_arquivo(arq):
    return (
        arq.get("url")
        or arq.get("uri")
        or arq.get("link")
        or arq.get("arquivo")
        or arq.get("downloadUrl")
    )


def ler_pdf_por_conteudo(conteudo):
    if not conteudo.startswith(b"%PDF"):
        try:
            decodificado = base64.b64decode(conteudo)
            if decodificado.startswith(b"%PDF"):
                conteudo = decodificado
        except Exception:
            return ""

    texto = ""
    try:
        doc = fitz.open(stream=conteudo, filetype="pdf")
        for pagina in doc:
            texto += pagina.get_text()
        doc.close()
    except Exception:
        return ""

    return texto


def ler_arquivos_importantes(link):
    arquivos, erro = buscar_arquivos_licitacao(link)
    if erro:
        return "", [], erro

    importantes = [a for a in arquivos if arquivo_eh_importante(a)]

    if not importantes and arquivos:
        importantes = arquivos[:3]

    texto_total = ""
    analisados = []
    headers = {"User-Agent": "Mozilla/5.0"}

    for arq in importantes[:8]:
        nome = str(arq.get("nome") or arq.get("titulo") or arq.get("name") or "Arquivo sem nome")
        tipo = str(arq.get("tipo") or arq.get("tipoDocumentoNome") or arq.get("tipo_documento_nome") or "Documento")

        try:
            if arq.get("conteudo_direto"):
                conteudo = arq["conteudo_direto"]
                url_pdf = pegar_url_arquivo(arq) or ""
            else:
                url_pdf = pegar_url_arquivo(arq)

                if not url_pdf:
                    continue

                if url_pdf.startswith("/"):
                    url_pdf = "https://pncp.gov.br" + url_pdf

                resp = requests.get(url_pdf, headers=headers, timeout=60)
                conteudo = resp.content

            texto = ler_pdf_por_conteudo(conteudo)

            if texto.strip():
                texto_total += f"\n\n===== ARQUIVO ANALISADO: {nome} | {tipo} =====\n\n"
                texto_total += texto
                analisados.append({
                    "nome": nome,
                    "tipo": tipo,
                    "url": url_pdf
                })

        except Exception:
            continue

    if not texto_total:
        return "", analisados, "Não consegui extrair texto dos arquivos importantes."

    return texto_total.lower(), analisados, ""


def extrair_secao(texto, inicios, fins, limite=180):
    linhas = texto.splitlines()
    coletando = False
    resultado = []

    for linha in linhas:
        linha_limpa = linha.strip()
        linha_lower = linha_limpa.lower()

        if not coletando and any(i in linha_lower for i in inicios):
            coletando = True

        if coletando:
            if len(linha_limpa) > 3:
                resultado.append(linha_limpa)

            if len(resultado) > 8 and any(f in linha_lower for f in fins):
                break

            if len(resultado) >= limite:
                break

    return resultado





def extrair_itens_reais(texto, palavras_inicio, palavras_fim, limite=120):
    """
    Extrai do edital somente itens específicos encontrados nas seções indicadas.
    Não inventa nada.
    Corrige frases quebradas pelo PDF, juntando apenas a continuação direta do item.
    """
    linhas = texto.split("\n")
    capturando = False
    encontrados = []
    item_atual = ""

    padrao_inicio_item = re.compile(r'^(\d+(\.\d+)*[\.\)]?|\-|\•|[a-z]\))\s+')

    termos_documentos = [
        "certidão",
        "certidao",
        "certificado",
        "regularidade",
        "balanço",
        "balanco",
        "demonstração contábil",
        "demonstracao contabil",
        "índice",
        "indice",
        "atestado",
        "capacidade técnica",
        "capacidade tecnica",
        "capacidade operacional",
        "fgts",
        "cndt",
        "cnpj",
        "sicaf",
        "caf",
        "declaração",
        "declaracao",
        "procuração",
        "procuracao",
        "garantia",
        "seguro-garantia",
        "seguro garantia",
        "fiança",
        "fianca",
        "caução",
        "caucao",
        "vistoria",
        "sei",
        "sistema eletrônico",
        "sistema eletronico",
        "assinatura do contrato",
        "prazo",
        "termo de referência",
        "termo de referencia",
        "obrigações",
        "obrigacoes",
        "execução",
        "execucao",
        "empresário individual",
        "empresario individual",
        "microempreendedor individual",
        "mei",
        "documentos pessoais",
        "sócios",
        "socios",
        "rg",
        "cpf",
        "cnh",
        "fazenda",
        "tributos",
        "trabalhistas",
        "falência",
        "falencia",
        "veículo",
        "veiculo",
        "crlv",
        "licenciamento",
        "motorista",
        "requerimento",
        "anexo"
    ]

    ignorar = [
        "universidade estadual",
        "pregoeira",
        "e-mail",
        "fls.",
        "página",
        "pagina",
        "portal nacional de contratações",
        "portal nacional de contratacoes",
        "rodovia",
        "campus",
        "subgerência",
        "subgerencia"
    ]

    def limpar(txt):
        txt = re.sub(r"\s+", " ", str(txt or ""))
        txt = txt.replace(" ;", ";").replace(" ,", ",").replace(" .", ".")
        txt = txt.replace(" :", ":")
        return txt.strip(" -•")

    def parece_continuacao(linha):
        """
        Considera continuação quando a linha não começa novo item
        e o item anterior parece estar incompleto.
        """
        if not item_atual:
            return False

        linha = limpar(linha)
        if not linha:
            return False

        linha_lower = linha.lower()

        if padrao_inicio_item.match(linha_lower):
            return False

        if any(i in linha_lower for i in ignorar):
            return False

        # Se o item anterior termina com pontuação forte, normalmente já acabou.
        atual = item_atual.strip()
        if atual.endswith("."):
            return False

        # Junta quando a linha anterior termina com conectivos ou vírgula,
        # ou quando a linha seguinte começa com palavra minúscula/preposição.
        conectivos_finais = (
            " da", " de", " do", " das", " dos", " para", " com", " sem",
            " mediante", " conforme", " perante", " durante", " que", " e",
            " ou", " no", " na", " nos", " nas", " pelo", " pela", "pelos", "pelas",
            "a", "o"
        )

        if atual.endswith(","):
            return True

        if any(atual.lower().endswith(c) for c in conectivos_finais):
            return True

        primeira = linha[:1]
        if primeira and primeira.islower():
            return True

        return False

    def salvar_item():
        nonlocal item_atual

        item = limpar(item_atual)

        if not item:
            item_atual = ""
            return

        item_lower = item.lower()

        genericas = [
            "documentos de habilitação",
            "documentos de habilitacao",
            "fase de habilitação",
            "fase de habilitacao",
            "documentação de habilitação",
            "documentacao de habilitacao",
            "documentação exigida para habilitação",
            "documentacao exigida para habilitacao"
        ]

        if item_lower in genericas:
            item_atual = ""
            return

        if len(item) >= 10:
            encontrados.append(item)

        item_atual = ""

    for linha in linhas:
        l = linha.strip()
        l_lower = l.lower()

        if not l:
            continue

        if not capturando and any(p in l_lower for p in palavras_inicio):
            capturando = True
            continue

        if not capturando:
            continue

        if any(i in l_lower for i in ignorar):
            continue

        # Para em nova seção de fim somente se não estiver no meio de item incompleto
        if len(encontrados) > 8 and not item_atual and any(p in l_lower for p in palavras_fim):
            break

        # Novo item numerado/bullet/alínea
        if padrao_inicio_item.match(l_lower):
            salvar_item()
            item_atual = l
            continue

        # Continuação direta do item anterior
        if parece_continuacao(l):
            item_atual += " " + l
            continue

        # Linha relevante sem numeração
        if any(k in l_lower for k in termos_documentos):
            salvar_item()
            item_atual = l
            continue

        # Caso não seja relevante e o item anterior já esteja completo, salva
        if item_atual:
            salvar_item()

        if len(encontrados) >= limite:
            break

    salvar_item()

    # Remove duplicados mantendo ordem
    final = []
    vistos = set()

    for item in encontrados:
        item_limpo = limpar(item)
        chave = item_limpo.lower()

        if not item_limpo:
            continue

        if chave not in vistos:
            final.append(item_limpo)
            vistos.add(chave)

    return final




def resumir_documentacao_habilitacao(texto):
    """
    Resume somente o que o edital indica como documentação de habilitação.
    Não copia texto bruto bagunçado; apresenta itens objetivos.
    """
    requisitos = []

    regras = {
        "Habilitação jurídica": [
            "habilitação jurídica",
            "habilitacao juridica",
            "ato constitutivo",
            "contrato social",
            "estatuto social",
            "registro comercial"
        ],

        "Regularidade fiscal": [
            "regularidade fiscal",
            "receita federal",
            "fazenda nacional",
            "fazenda estadual",
            "fazenda municipal",
            "cnpj"
        ],

        "Regularidade trabalhista": [
            "regularidade trabalhista",
            "débitos trabalhistas",
            "debitos trabalhistas",
            "cndt"
        ],

        "Regularidade com FGTS": [
            "fgts",
            "fundo de garantia"
        ],

        "Qualificação técnica": [
            "qualificação técnica",
            "qualificacao tecnica",
            "capacidade técnica",
            "capacidade tecnica"
        ],

        "Atestado de capacidade técnica": [
            "atestado de capacidade técnica",
            "atestado de capacidade tecnica",
            "atestado técnico",
            "atestado tecnico"
        ],

        "Qualificação econômico-financeira": [
            "qualificação econômico-financeira",
            "qualificacao economico-financeira",
            "econômico-financeira",
            "economico-financeira"
        ],

        "Balanço patrimonial e índices contábeis": [
            "balanço patrimonial",
            "balanco patrimonial",
            "índices contábeis",
            "indices contabeis",
            "liquidez geral",
            "solvência geral",
            "solvencia geral"
        ],

        "Certidão negativa de falência/recuperação judicial": [
            "falência",
            "falencia",
            "recuperação judicial",
            "recuperacao judicial",
            "concordata"
        ],

        "Declarações exigidas no edital": [
            "declaração",
            "declaracao",
            "declarações",
            "declaracoes"
        ],

        "Declaração ME/EPP, quando aplicável": [
            "me/epp",
            "microempresa",
            "empresa de pequeno porte"
        ],

        "Procuração do representante, se houver": [
            "procuração",
            "procuracao",
            "procurador"
        ],

        "Cadastro no SICAF/CAF ou registro cadastral equivalente": [
            "sicaf",
            "caf",
            "registro cadastral",
            "cadastro de fornecedores"
        ]
    }

    for titulo, palavras in regras.items():
        if any(p in texto for p in palavras):
            requisitos.append(titulo)

    return requisitos


def resumir_exigencias_contratacao(texto):
    """
    Resume somente as exigências contratuais localizadas no edital.
    Mostra a seção apenas quando algum requisito for identificado.
    """
    exigencias = []

    regras = {
        "Assinatura do contrato": [
            "assinatura do contrato",
            "assinar o contrato",
            "convocado para assinar"
        ],

        "Prazo para assinatura do contrato": [
            "prazo para assinatura",
            "assinar o contrato no prazo",
            "10 dias",
            "dez dias"
        ],

        "Assinatura/cadastramento em sistema eletrônico ou SEI": [
            "sei",
            "sistema eletrônico de informações",
            "sistema eletronico de informacoes",
            "sistema eletrônico",
            "sistema eletronico"
        ],

        "Garantia contratual": [
            "garantia contratual",
            "garantia da contratação",
            "garantia da contratacao",
            "seguro-garantia",
            "seguro garantia",
            "fiança bancária",
            "fianca bancaria",
            "caução",
            "caucao"
        ],

        "Execução conforme Termo de Referência": [
            "termo de referência",
            "termo de referencia",
            "executar o objeto",
            "execução do objeto",
            "execucao do objeto"
        ],

        "Prazo de execução/entrega": [
            "prazo de execução",
            "prazo de execucao",
            "prazo de entrega",
            "entrega do objeto"
        ],

        "Vistoria técnica ou declaração de ciência": [
            "vistoria técnica",
            "vistoria tecnica",
            "declaração de vistoria",
            "declaracao de vistoria",
            "ciência das condições",
            "ciencia das condicoes"
        ],

        "Responsabilidade por custos, encargos, tributos e despesas da proposta": [
            "custos operacionais",
            "tributos",
            "encargos",
            "despesas",
            "proposta compreende"
        ],

        "Cumprimento das obrigações da contratada": [
            "obrigações da contratada",
            "obrigacoes da contratada",
            "contratada deverá",
            "contratada devera"
        ]
    }

    for titulo, palavras in regras.items():
        if any(p in texto for p in palavras):
            exigencias.append(titulo)

    return exigencias


def formularios_identificados(texto):
    """
    Identifica apenas modelos/formulários reais no edital.
    Não usa 'anexo' sozinho para evitar falso positivo.
    """
    tipos = []

    regras = {
        "Modelo de Proposta de Preços": [
            "modelo de proposta de preços",
            "modelo de proposta de precos",
            "modelo de proposta"
        ],

        "Declaração de Elaboração Independente de Proposta": [
            "declaração de elaboração independente de proposta",
            "declaracao de elaboracao independente de proposta",
            "elaboração independente de proposta",
            "elaboracao independente de proposta"
        ],

        "Modelo de Procuração": [
            "modelo de procuração",
            "modelo de procuracao"
        ],

        "Modelo de Declaração para ME/EPP": [
            "modelo de declaração para me/epp",
            "modelo de declaracao para me/epp",
            "declaração para me/epp",
            "declaracao para me/epp",
            "declaração por me e epp",
            "declaracao por me e epp"
        ],

        "Modelo de Prova de Capacidade Operacional": [
            "modelo de prova de capacidade operacional",
            "prova de capacidade operacional"
        ],

        "Modelo de Declaração de Ciência das Condições da Licitação/Vistoria": [
            "modelo de declaração de ciência das condições",
            "modelo de declaracao de ciencia das condicoes",
            "declaração de ciência das condições",
            "declaracao de ciencia das condicoes",
            "declaração de vistoria",
            "declaracao de vistoria"
        ],
    }

    for nome, palavras in regras.items():
        if any(p in texto for p in palavras):
            tipos.append(nome)

    return tipos



def li(lista):
    if not lista:
        return ""
    return "".join([f"<li>{escape(x)}</li>" for x in lista])


def organizar_texto_edital(texto):
    texto = texto.replace("\r", "\n")

    # Remove linhas vazias excessivas
    texto = re.sub(r'\n\s*\n+', '\n\n', texto)

    # Quebra antes de itens numerados quando aparecem no meio de frase
    texto = re.sub(
        r'([a-záéíóúãõç])\s+(\d+\.\d+)',
        r'\1\n\n\2',
        texto
    )

    # Organiza itens e subitens: 10.1 / 10.1.1 / 15.1.2
    texto = re.sub(
        r'(\d+\.\d+(?:\.\d+)*)\s*',
        r'\n\1 ',
        texto
    )

    # Quebra frases grandes sem destruir tabelas
    texto = re.sub(
        r'([.;])\s+(?=[A-ZÁÉÍÓÚÃÕÇ])',
        r'\1\n',
        texto
    )

    # Remove espaços duplicados
    texto = re.sub(r'[ \t]+', ' ', texto)

    # Remove linhas vazias demais
    texto = re.sub(r'\n{3,}', '\n\n', texto)

    return texto.strip()


def texto_bloco(lista):
    if not lista:
        return ""

    texto = "\n".join(lista)
    texto = organizar_texto_edital(texto)

    return escape(texto)



def arquivos_html(arquivos):
    if not arquivos:
        return "<li>Nenhum arquivo analisado.</li>"

    html = ""
    for a in arquivos:
        nome = escape(a.get("nome", "Arquivo"))
        tipo = escape(a.get("tipo", "Documento"))
        url = escape(a.get("url", "#"))
        html += f"<li><b>{nome}</b> — {tipo} — <a href='{url}' target='_blank'>abrir</a></li>"
    return html


def css_relatorio():
    return """
    <style>
    *{box-sizing:border-box}
    body{
        font-family:Arial, Helvetica, sans-serif;
        background:#f3f6fb;
        padding:32px;
        color:#081f4d;
    }
    .page{
        background:white;
        max-width:1180px;
        margin:auto;
        padding:34px;
        border-radius:22px;
        box-shadow:0 16px 40px rgba(8,31,77,.08);
    }
    h1{
        color:#061f63;
        font-size:34px;
        margin-bottom:8px;
        letter-spacing:-.5px;
    }
    .subinfo{
        color:#5b6d95;
        line-height:1.6;
        margin-bottom:18px;
        font-size:15px;
    }
    .bloco{
        background:#f8fbff;
        border:1px solid #dfe8f5;
        border-left:6px solid #0a47ff;
        padding:22px;
        border-radius:16px;
        margin-bottom:20px;
    }
    .bloco h3{
        margin:0 0 12px 0;
        color:#0a2a7a;
        font-size:22px;
        display:flex;
        align-items:center;
        gap:8px;
    }
    .bloco p,.bloco li{
        font-size:15px;
        line-height:1.7;
        color:#233653;
    }
    .bloco ul{padding-left:0;margin:0;list-style:none}
    .bloco > ul li{
        background:white;
        border:1px solid #e0e8f5;
        border-radius:10px;
        padding:10px 12px 10px 36px;
        margin-bottom:8px;
        position:relative;
    }
    .bloco > ul li:before{
        content:"✓";
        position:absolute;
        left:12px;
        top:9px;
        color:#0a47ff;
        font-weight:900;
    }
    .categoria{
        background:#ffffff;
        border:1px solid #dbe4f2;
        border-radius:14px;
        padding:16px;
        margin-top:14px;
        box-shadow:0 6px 18px rgba(8,31,77,.04);
    }
    .categoria h4{
        font-size:17px;
        color:#0a2a7a;
        margin:0 0 10px 0;
        padding-bottom:8px;
        border-bottom:1px solid #edf2f8;
    }
    .categoria ul{
        padding-left:0;
        margin:0;
        list-style:none;
    }
    .categoria li{
        background:#f8fbff;
        border:1px solid #e5edf7;
        border-radius:12px;
        padding:14px 16px 14px 42px;
        margin-bottom:12px;
        position:relative;
        line-height:1.9;
        font-size:15px;
        word-break:break-word;
        overflow-wrap:anywhere;
        white-space:normal;
        text-align:left;
    }
    .categoria li:before{
        content:"✓";
        position:absolute;
        left:14px;
        top:13px;
        color:#0a47ff;
        font-weight:900;
        font-size:16px;
    }
    .info-grid{
        display:grid;
        grid-template-columns:1.4fr 1fr 1fr;
        gap:14px;
        margin-bottom:20px;
        align-items:stretch;
    }
    .info-card{
        background:#f8fbff;
        border:1px solid #dfe8f5;
        border-radius:16px;
        padding:18px;
    }
    .info-card h3{
        margin:0 0 8px 0;
        color:#0a2a7a;
        font-size:18px;
    }
    .info-card p,.info-card li{
        color:#233653;
        font-size:15px;
        line-height:1.7;
        word-break:break-word;
        overflow-wrap:anywhere;
    }
    .info-card ul{
        margin:0;
        padding-left:18px;
    }
    .actions{
        margin-top:22px;
        display:flex;
        gap:10px;
        flex-wrap:wrap;
    }
    .btn{
        padding:10px 16px;
        border:0;
        border-radius:10px;
        background:#0a47ff;
        color:white;
        font-weight:bold;
        cursor:pointer;
        margin-right:8px;
        text-decoration:none;
        display:inline-block;
    }
    .btn2{
        padding:10px 16px;
        border:1px solid #ccd7e6;
        border-radius:10px;
        background:white;
        color:#081f4d;
        font-weight:bold;
        cursor:pointer;
        text-decoration:none;
        display:inline-block;
    }
    .campo{
        border-bottom:1px solid #333;
        display:inline-block;
        min-width:280px;
        height:22px;
    }
    .texto-edital{
        white-space:pre-wrap;
        background:#ffffff;
        border:1px solid #dbe4f2;
        padding:22px;
        border-radius:12px;
        font-family:Arial, Helvetica, sans-serif;
        font-size:15px;
        line-height:1.9;
        overflow:auto;
        color:#1f2d3d;
        text-align:left;
        word-break:break-word;
    }
    @media(max-width:900px){
        body{padding:14px}
        .page{padding:20px}
        .info-grid{grid-template-columns:1fr}
    }
    @media print{
        button,.btn,.btn2,.actions{display:none}
        body{background:white;padding:0}
        .page{box-shadow:none;margin:0;max-width:none;border-radius:0}
    }
    </style>
    """


@app.get("/", response_class=HTMLResponse)
def home():
    return """
<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="UTF-8">
<title>RETT Premium</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.amcharts.com/lib/5/index.js"></script>
<script src="https://cdn.amcharts.com/lib/5/map.js"></script>
<script src="https://cdn.amcharts.com/lib/5/geodata/brazilLow.js"></script>
<script src="https://cdn.amcharts.com/lib/5/themes/Animated.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:Arial,Helvetica,sans-serif}
body{background:#f4f7fc;color:#081f4d}.wrapper{display:flex;min-height:100vh}
.sidebar{width:230px;background:#fff;padding:22px;border-right:1px solid #e8eef7;position:fixed;left:0;top:0;bottom:0}
.logo{font-size:42px;font-weight:900;color:#0a47ff;margin-bottom:25px}.logo span{font-size:18px;letter-spacing:8px}
.menu a{display:block;padding:14px;margin-bottom:8px;border-radius:12px;text-decoration:none;color:#0b2153;font-weight:700;cursor:pointer}
.menu a.active{background:#0a47ff;color:#fff}.menu a:hover{background:#edf3ff}
.content{flex:1;padding:24px;margin-left:230px}.top{display:flex;justify-content:space-between;align-items:center}
.title{font-size:56px;font-style:italic;font-family:Georgia,serif;font-weight:700;color:#071b63;line-height:1}
.subtitle{font-size:20px;color:#0a47ff;font-weight:800;margin-top:4px}.user{font-weight:800;font-size:22px}
.searchbar{display:flex;gap:10px;margin-top:18px}.searchbar input{flex:1;height:56px;border:1px solid #dbe4f2;border-radius:14px;padding:0 18px;font-size:17px}
.searchbar select{height:56px;border:1px solid #dbe4f2;border-radius:14px;padding:0 14px;font-size:15px;font-weight:700;color:#081f4d;background:white;min-width:170px}
.searchbar button{width:150px;border:none;background:#0a47ff;color:#fff;font-weight:800;font-size:16px;border-radius:14px;cursor:pointer}
.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-top:18px}.card{background:#fff;border-radius:18px;padding:18px;box-shadow:0 10px 24px rgba(0,0,0,.04)}
.card h4{font-size:13px;color:#5b6d95}.card h2{font-size:34px;margin-top:10px;color:#081f4d}
.grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-top:16px}.panel{background:#fff;border-radius:18px;padding:18px;box-shadow:0 10px 24px rgba(0,0,0,.04);min-height:340px;overflow:hidden}
#mapaBrasil{width:100%;height:310px}.panel canvas{width:100%!important;height:270px!important}
.table-box{background:#fff;border-radius:18px;padding:18px;box-shadow:0 10px 24px rgba(0,0,0,.04);margin-top:16px;overflow-x:auto}
.table-header{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:10px}
.table-header h3{margin:0}
.table-filters{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.table-filters select{height:40px;border:1px solid #dbe4f2;border-radius:10px;padding:0 12px;font-size:13px;font-weight:800;color:#081f4d;background:white;min-width:120px}
.table-filters select:nth-child(2){min-width:210px}
.btn-clear-filter{height:40px;border:1px solid #dbe4f2;background:#fff;color:#081f4d;border-radius:10px;padding:0 14px;font-weight:800;cursor:pointer}
.btn-clear-filter:hover{background:#edf3ff}
table{width:100%;border-collapse:collapse;margin-top:10px}th{background:#f3f6fb;padding:12px;text-align:left;font-size:13px}
td{padding:12px;border-bottom:1px solid #edf1f7;font-size:13px;vertical-align:top}.badge{padding:6px 10px;border-radius:8px;font-weight:800;font-size:12px;display:inline-block}
.blue{background:#e8f0ff;color:#0a47ff}.action{display:inline-block;color:#fff;padding:7px 10px;border-radius:8px;text-decoration:none;font-size:12px;font-weight:800;margin:2px}
.open{background:#0a47ff}.ai{background:#8d35ff}
.paginacao{display:flex;justify-content:center;gap:10px;margin-top:18px}.paginacao button{padding:10px 16px;border:1px solid #dbe4f2;background:#fff;border-radius:10px;font-weight:800;cursor:pointer}
.paginacao button.ativo{background:#0a47ff;color:#fff}.filtro-info{margin-top:10px;font-weight:800;color:#0a47ff}
@media(max-width:1200px){.cards{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}.sidebar{display:none}.content{margin-left:0}}
</style>
</head>
<body>
<div class="wrapper">
<div class="sidebar">
<div class="logo">R<span>ETT</span></div>
<div class="menu">
<a class="active">🏠 Dashboard</a>
<a onclick="document.getElementById('busca').focus()">🔎 Buscar Licitações</a>
<a>💎 Oportunidades</a>
<a>⭐ Favoritos</a>
<a>📊 Relatórios</a>
<a>⚙️ Configurações</a>
</div>
</div>
<div class="content">
<div class="top">
<div><div class="title">Plataforma de Acesso</div><div class="subtitle">ao Setor Público Brasileiro</div></div>
<div class="user">Olá, Admin</div>
</div>
<div class="searchbar">
<input id="busca" placeholder="Digite motorista, limpeza, medicamento, engenharia...">
<button onclick="limparFiltrosEBuscar()">Pesquisar</button>
</div>
<div class="cards">
<div class="card"><h4>TOTAL BRASIL PNCP</h4><h2 id="totPncp">Carregando...</h2></div>
<div class="card"><h4>PÁGINA ATUAL</h4><h2 id="pagAtual">1</h2></div>
<div class="card"><h4>UF</h4><h2 id="cardUf">Brasil</h2></div>
<div class="card"><h4>MODALIDADE</h4><h2 id="cardMod">Todas</h2></div>
<div class="card"><h4>FONTE</h4><h2>PNCP</h2></div>
</div>
<div class="grid">
<div class="panel"><h3>Por Modalidade</h3><small>Clique em uma modalidade para filtrar</small><canvas id="graf1"></canvas></div>
<div class="panel"><h3>Mapa Real do Brasil</h3><small>Clique em um estado para filtrar</small><div id="mapaBrasil"></div></div>
<div class="panel"><h3>IA de Edital</h3><small>Análise automática do edital</small><br><br>
<p>O sistema filtra pelo objeto da licitação e lê o edital para identificar habilitação, exigências e formulários.</p>
<div class="filtro-info" id="filtroInfo">Brasil inteiro | Todas as modalidades</div><br>
<button onclick="limparFiltrosEBuscar()" style="padding:10px 14px;border:0;border-radius:10px;background:#0a47ff;color:white;font-weight:800;cursor:pointer">Brasil inteiro</button>
</div>
</div>
<div class="table-box">
<div class="table-header">
    <h3>Licitações Reais do PNCP</h3>

    <div class="table-filters">
        <select id="filtroUfSelect" onchange="aplicarFiltrosTopo()">
            <option value="">UF</option>
            <option value="AC">AC</option>
            <option value="AL">AL</option>
            <option value="AP">AP</option>
            <option value="AM">AM</option>
            <option value="BA">BA</option>
            <option value="CE">CE</option>
            <option value="DF">DF</option>
            <option value="ES">ES</option>
            <option value="GO">GO</option>
            <option value="MA">MA</option>
            <option value="MT">MT</option>
            <option value="MS">MS</option>
            <option value="MG">MG</option>
            <option value="PA">PA</option>
            <option value="PB">PB</option>
            <option value="PR">PR</option>
            <option value="PE">PE</option>
            <option value="PI">PI</option>
            <option value="RJ">RJ</option>
            <option value="RN">RN</option>
            <option value="RS">RS</option>
            <option value="RO">RO</option>
            <option value="RR">RR</option>
            <option value="SC">SC</option>
            <option value="SP">SP</option>
            <option value="SE">SE</option>
            <option value="TO">TO</option>
        </select>

        <select id="filtroModalidadeSelect" onchange="aplicarFiltrosTopo()">
            <option value="">Modalidade</option>
            <option value="Pregão - Eletrônico">Pregão - Eletrônico</option>
            <option value="Concorrência - Eletrônica">Concorrência - Eletrônica</option>
            <option value="Dispensa">Dispensa</option>
            <option value="Credenciamento">Credenciamento</option>
            <option value="Leilão">Leilão</option>
        </select>

        <button class="btn-clear-filter" onclick="limparFiltrosTabela()">Limpar</button>
    </div>
</div>
<table>
<thead><tr><th>Órgão</th><th>Objeto</th><th>UF</th><th>Modalidade</th><th>Início Proposta</th><th>Fim Proposta</th><th>Ações</th></tr></thead>
<tbody id="resultado"><tr><td colspan="7">Carregando licitações do Brasil...</td></tr></tbody>
</table>
<div class="paginacao"><button onclick="voltarPagina()">‹ Anterior</button><button class="ativo" id="paginaTexto">Página 1</button><button onclick="proximaPagina()">Próxima ›</button></div>
</div>
</div>
</div>

<script>
let paginaAtual=1, filtroModalidade="", filtroUF="", graficoModalidade=null, polygonSeries=null;

function formatarData(v){if(!v||v=="-")return "-";let d=v.substring(0,10),h=v.substring(11,16),p=d.split("-");return p.length==3?`${p[2]}/${p[1]}/${p[0]} ${h}`:v}
function formatarValor(v){if(!v||v=="-"||v==null)return "-";let n=Number(v);return isNaN(n)?"-":n.toLocaleString('pt-BR',{style:'currency',currency:'BRL'})}
function atualizarCardsEFiltros(){
document.getElementById("cardUf").innerText=filtroUF||"Brasil";
document.getElementById("cardMod").innerText=filtroModalidade?filtroModalidade.split(" ")[0]:"Todas";
document.getElementById("filtroInfo").innerText=(filtroUF?("UF: "+filtroUF):"Brasil inteiro")+" | "+(filtroModalidade?("Modalidade: "+filtroModalidade):"Todas as modalidades");

let ufSelect=document.getElementById("filtroUfSelect");
let modSelect=document.getElementById("filtroModalidadeSelect");
if(ufSelect){ufSelect.value=filtroUF||""}
if(modSelect){modSelect.value=filtroModalidade||""}
}

function aplicarFiltrosTopo(){
let ufSelect=document.getElementById("filtroUfSelect");
let modSelect=document.getElementById("filtroModalidadeSelect");

filtroUF=ufSelect?ufSelect.value:"";
filtroModalidade=modSelect?modSelect.value:"";

buscar(1);
}
function atualizarGraficoModalidade(modalidades){
let labels=Object.keys(modalidades), valores=Object.values(modalidades);
if(labels.length===0){labels=["Sem dados"];valores=[1]}
if(graficoModalidade){graficoModalidade.destroy()}
graficoModalidade=new Chart(document.getElementById('graf1'),{
type:'doughnut',
data:{labels:labels,datasets:[{data:valores,backgroundColor:['#0a47ff','#33c3ff','#ff6900','#8d35ff','#14b85a','#ff3b30','#64748b'],borderWidth:0}]},
options:{responsive:true,maintainAspectRatio:false,cutout:'62%',plugins:{legend:{position:'top'}},onClick:function(evt,e){if(e.length>0){filtroModalidade=graficoModalidade.data.labels[e[0].index];buscar(1)}}}
});
}
function atualizarMapa(ufs){
let dadosMapa=[];Object.keys(ufs).forEach(uf=>dadosMapa.push({id:"BR-"+uf,value:ufs[uf],uf:uf}));
if(polygonSeries){polygonSeries.data.setAll(dadosMapa)}
}
am5.ready(function(){
let root=am5.Root.new("mapaBrasil");root.setThemes([am5themes_Animated.new(root)]);
let chart=root.container.children.push(am5map.MapChart.new(root,{panX:"none",panY:"none",wheelX:"none",wheelY:"none",projection:am5map.geoMercator()}));
polygonSeries=chart.series.push(am5map.MapPolygonSeries.new(root,{geoJSON:am5geodata_brazilLow,valueField:"value",calculateAggregates:true}));
polygonSeries.mapPolygons.template.setAll({tooltipText:"{name}: {value} licitações",interactive:true,fill:am5.color(0xbcd8ff),stroke:am5.color(0xffffff),strokeWidth:1});
polygonSeries.set("heatRules",[{target:polygonSeries.mapPolygons.template,dataField:"value",min:am5.color(0xbcd8ff),max:am5.color(0x0a47ff),key:"fill"}]);
polygonSeries.mapPolygons.template.events.on("click",function(ev){let data=ev.target.dataItem.dataContext;if(data&&data.id){filtroUF=data.id.replace("BR-","");buscar(1)}});
});
function limparFiltrosEBuscar(){
filtroModalidade="";
filtroUF="";
let ufSelect=document.getElementById("filtroUfSelect");
let modSelect=document.getElementById("filtroModalidadeSelect");
if(ufSelect){ufSelect.value=""}
if(modSelect){modSelect.value=""}
buscar(1);
}

function limparFiltrosTabela(){
filtroModalidade="";
filtroUF="";
let ufSelect=document.getElementById("filtroUfSelect");
let modSelect=document.getElementById("filtroModalidadeSelect");
if(ufSelect){ufSelect.value=""}
if(modSelect){modSelect.value=""}
buscar(1);
}
async function buscar(pagina){
paginaAtual=pagina;
let termo=document.getElementById("busca").value.trim();
let url="/buscar?q="+encodeURIComponent(termo)+"&pagina="+paginaAtual;
if(filtroModalidade){url+="&modalidade="+encodeURIComponent(filtroModalidade)}
if(filtroUF){url+="&uf="+encodeURIComponent(filtroUF)}
let r=await fetch(url), dados=await r.json();
document.getElementById("totPncp").innerText=dados.total_pncp;
document.getElementById("pagAtual").innerText=dados.pagina;
document.getElementById("paginaTexto").innerText="Página "+dados.pagina;
atualizarGraficoModalidade(dados.modalidades||{});atualizarMapa(dados.ufs||{});atualizarCardsEFiltros();
let html="";
if(dados.items.length==0){html="<tr><td colspan='7'>Nenhum resultado encontrado.</td></tr>"}
else{dados.items.forEach(i=>{
let analisar="/analisar?link="+encodeURIComponent(i.link)+"&objeto="+encodeURIComponent(i.objeto)+"&orgao="+encodeURIComponent(i.orgao)+"&modalidade="+encodeURIComponent(i.modalidade)+"&valor="+encodeURIComponent(i.valor);
html+=`<tr><td>${i.orgao}</td><td>${i.objeto}</td><td>${i.uf}</td><td><span class='badge blue'>${i.modalidade}</span></td><td>${formatarData(i.inicio)}</td><td>${formatarData(i.fim)}</td><td><a class='action open' target='_blank' href='${i.link}'>Abrir</a><a class='action ai' href='${analisar}'>Analisar</a></td></tr>`;
})}
document.getElementById("resultado").innerHTML=html;
}
function proximaPagina(){buscar(paginaAtual+1)}
function voltarPagina(){if(paginaAtual>1)buscar(paginaAtual-1)}
window.onload=function(){buscar(1)}
</script>
</body>
</html>
"""


@app.get("/analisar", response_class=HTMLResponse)
def analisar(link: str = "", objeto: str = "", orgao: str = "", modalidade: str = "", valor: str = ""):
    link = unquote(link)
    objeto = unquote(objeto)
    orgao = unquote(orgao)
    modalidade = unquote(modalidade)
    valor = unquote(valor)

    texto, arquivos, erro = ler_arquivos_importantes(link)

    docs = extrair_itens_reais(
        texto,
        [
            "documentação exigida para habilitação",
            "documentacao exigida para habilitacao",
            "documentação de habilitação",
            "documentacao de habilitacao",
            "documentos de habilitação",
            "documentos de habilitacao",
            "habilitação jurídica",
            "habilitacao juridica",
            "regularidade fiscal",
            "regularidade trabalhista",
            "qualificação técnica",
            "qualificacao tecnica",
            "qualificação econômico-financeira",
            "qualificacao economico-financeira",
            "comprovação dos requisitos de habilitação",
            "comprovacao dos requisitos de habilitacao"
        ],
        [
            "recurso",
            "adjudicação",
            "adjudicacao",
            "homologação",
            "homologacao",
            "assinatura do contrato",
            "contratação",
            "contratacao",
            "pagamento",
            "sanções",
            "sancoes",
            "disposições finais",
            "disposicoes finais"
        ],
        limite=120
    )
    exig = extrair_itens_reais(
        texto,
        [
            "prazo para assinatura do contrato",
            "assinatura do contrato",
            "formalização da contratação",
            "formalizacao da contratacao",
            "condições para contratação",
            "condicoes para contratacao",
            "garantia contratual",
            "obrigações da contratada",
            "obrigacoes da contratada",
            "execução do objeto",
            "execucao do objeto",
            "prazo de execução",
            "prazo de execucao",
            "vistoria"
        ],
        [
            "pagamento",
            "fiscalização",
            "fiscalizacao",
            "sanções",
            "sancoes",
            "penalidades",
            "rescisão",
            "rescisao",
            "foro",
            "disposições finais",
            "disposicoes finais",
            "anexo"
        ],
        limite=100
    )
    forms = formularios_identificados(texto)

    aviso = f"<div class='bloco'><h3>⚠️ Observação</h3><p>{escape(erro)}</p></div>" if erro else ""

    bloco_docs = ""
    if docs:
        bloco_docs = f"""
        <div class="bloco">
            <h3>📄 Documentação Exigida para Habilitação</h3>
            <p class="subinfo">Itens específicos identificados no edital:</p>
            <ul>{li(docs)}</ul>
        </div>
        """

    bloco_exig = ""
    if exig:
        bloco_exig = f"""
        <div class="bloco">
            <h3>🛠️ Exigências para Contratação</h3>
            <p class="subinfo">Exigências específicas identificadas no edital:</p>
            <ul>{li(exig)}</ul>
        </div>
        """

    bloco_forms = ""
    if forms:
        link_form = "/formularios?link=" + quote(link) + "&objeto=" + quote(objeto)
        bloco_forms = f"""
        <div class="bloco">
            <h3>📑 Formulários Identificados no Edital</h3>
            <ul>{li(forms)}</ul>
            <br>
            <a class="btn" href="{link_form}">Gerar documento para preenchimento</a>
        </div>
        """

    return f"""
    <html>
    <head>
    <meta charset="UTF-8">
    <title>Análise Inteligente do Edital</title>
    {css_relatorio()}
    </head>
    <body>
    <div class="page">
    <h1>📑 Resumo Estruturado do Edital</h1>
    <p class="subinfo">
    O sistema analisou automaticamente os arquivos importantes da licitação e extraiu somente as informações localizadas no edital.
    </p>

    <div class="info-grid">
        <div class="info-card">
            <h3>📌 Objeto</h3>
            <p>{escape(objeto) if objeto else "Não informado."}</p>
        </div>

        <div class="info-card">
            <h3>🏢 Órgão</h3>
            <p>{escape(orgao) if orgao else "Não informado."}</p>
        </div>

        <div class="info-card">
            <h3>📋 Licitação</h3>
            <ul>
                <li><b>Modalidade:</b> {escape(modalidade) if modalidade else "Não informado."}</li>
                <li><b>Link oficial:</b> <a href="{escape(link)}" target="_blank">Abrir no PNCP</a></li>
            </ul>
        </div>
    </div>

    {aviso}
    {bloco_docs}
    {bloco_exig}
    {bloco_forms}

    <div class="bloco">
        <h3>📚 Arquivos Analisados</h3>
        <ul>{arquivos_html(arquivos)}</ul>
    </div>

    <div class="actions">
        <button class="btn" onclick="window.print()">Gerar PDF</button>
        <button class="btn2" onclick="history.back()">Voltar</button>
    </div>
    </div>
    </body>
    </html>
    """


def formulario_html(nome):
    if nome == "Modelo de Proposta de Preços":
        return """
        <div class="bloco">
            <h3>1. Modelo de Proposta de Preços</h3>
            <p>Razão Social: <span class="campo"></span></p>
            <p>CNPJ: <span class="campo"></span></p>
            <p>Objeto/Lote: <span class="campo"></span></p>
            <p>Valor unitário: <span class="campo"></span></p>
            <p>Valor total: <span class="campo"></span></p>
            <p>Prazo de validade da proposta: <span class="campo"></span></p>
            <p>Local e data: <span class="campo"></span></p>
            <p>Assinatura do representante legal: <span class="campo"></span></p>
        </div>
        """

    if nome == "Declaração de Elaboração Independente de Proposta":
        return """
        <div class="bloco">
            <h3>2. Declaração de Elaboração Independente de Proposta</h3>
            <p>A empresa <span class="campo"></span>, inscrita no CNPJ nº <span class="campo"></span>, declara que elaborou sua proposta de forma independente, sem acordo, combinação ou ajuste com terceiros, conforme exigido no edital.</p>
            <p>Local e data: <span class="campo"></span></p>
            <p>Assinatura: <span class="campo"></span></p>
        </div>
        """

    if nome == "Modelo de Procuração":
        return """
        <div class="bloco">
            <h3>3. Modelo de Procuração</h3>
            <p>Outorgante/Razão Social: <span class="campo"></span></p>
            <p>CNPJ: <span class="campo"></span></p>
            <p>Representante legal: <span class="campo"></span></p>
            <p>CPF do representante legal: <span class="campo"></span></p>
            <p>Procurador: <span class="campo"></span></p>
            <p>CPF do procurador: <span class="campo"></span></p>
            <p>Poderes concedidos: representar a empresa na licitação, apresentar propostas, formular lances, assinar declarações, interpor ou desistir de recursos e praticar os demais atos necessários.</p>
            <p>Local e data: <span class="campo"></span></p>
            <p>Assinatura: <span class="campo"></span></p>
        </div>
        """

    if nome == "Modelo de Declaração para ME/EPP":
        return """
        <div class="bloco">
            <h3>4. Declaração ME/EPP</h3>
            <p>A empresa <span class="campo"></span>, CNPJ nº <span class="campo"></span>, declara, sob as penas da lei, que se enquadra como Microempresa ou Empresa de Pequeno Porte e que atende às condições previstas no edital e na legislação aplicável.</p>
            <p>Local e data: <span class="campo"></span></p>
            <p>Assinatura: <span class="campo"></span></p>
        </div>
        """

    if nome == "Modelo de Prova de Capacidade Operacional":
        return """
        <div class="bloco">
            <h3>5. Prova de Capacidade Operacional</h3>
            <p>Empresa/órgão emissor do atestado: <span class="campo"></span></p>
            <p>CNPJ: <span class="campo"></span></p>
            <p>Atestamos que a empresa <span class="campo"></span>, CNPJ nº <span class="campo"></span>, executou serviços compatíveis com o objeto da licitação, apresentando desempenho satisfatório.</p>
            <p>Descrição dos serviços executados: <span class="campo"></span></p>
            <p>Período de execução: <span class="campo"></span></p>
            <p>Responsável pela emissão: <span class="campo"></span></p>
            <p>Assinatura/carimbo: <span class="campo"></span></p>
        </div>
        """

    if nome == "Modelo de Declaração de Ciência das Condições da Licitação/Vistoria":
        return """
        <div class="bloco">
            <h3>6. Declaração de Ciência das Condições da Licitação/Vistoria</h3>
            <p>A empresa <span class="campo"></span>, CNPJ nº <span class="campo"></span>, declara que tomou ciência das condições de execução do objeto da licitação, inclusive quanto às condições locais, técnicas e operacionais necessárias ao cumprimento contratual.</p>
            <p>Responsável pela vistoria/declaração: <span class="campo"></span></p>
            <p>CPF: <span class="campo"></span></p>
            <p>Local e data: <span class="campo"></span></p>
            <p>Assinatura: <span class="campo"></span></p>
        </div>
        """

    return ""


@app.get("/formularios", response_class=HTMLResponse)
def formularios(link: str = "", objeto: str = ""):
    link = unquote(link)
    objeto = unquote(objeto)

    texto, arquivos, erro = ler_arquivos_importantes(link)
    forms = formularios_identificados(texto)

    if not forms:
        return f"""
        <html><head>{css_relatorio()}</head>
        <body><div class="page">
        <h1>📑 Formulários Identificados no Edital</h1>
        <div class="bloco">
            <h3>Resultado</h3>
            <p>Nenhum formulário/modelo oficial foi identificado automaticamente no edital.</p>
        </div>
        <button class="btn2" onclick="location.href='/'">Voltar</button>
        </div></body></html>
        """

    formularios_gerados = "".join(formulario_html(f) for f in forms)

    return f"""
    <html>
    <head>
    <meta charset="UTF-8">
    <title>Formulários para Preenchimento</title>
    {css_relatorio()}
    </head>
    <body>
    <div class="page">
    <h1>📑 Formulários para Preenchimento da Empresa</h1>
    <p class="subinfo">Documento gerado somente porque o edital possui modelos/formulários identificados automaticamente.</p>

    <div class="bloco">
        <h3>📌 Objeto</h3>
        <p>{escape(objeto)}</p>
    </div>

    <div class="bloco">
        <h3>📑 Modelos/Formulários Identificados no Edital</h3>
        <ul>{li(forms)}</ul>
    </div>

    {formularios_gerados}

    <div class="actions">
        <button class="btn" onclick="window.print()">Gerar PDF</button>
        <button class="btn2" onclick="history.back()">Voltar</button>
    </div>
    </div>
    </body>
    </html>
    """
