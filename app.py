from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import requests
import re
import json

app = FastAPI()
RESULTADOS_POR_PAGINA = 20


@app.get("/", response_class=HTMLResponse)
def inicio():
    return """
<!DOCTYPE html>
<html>
<head>
<title>Painel PNCP Inteligente</title>
<style>
body{font-family:Arial;background:#f4f6fb;padding:30px;}
.box{background:white;padding:25px;border-radius:15px;box-shadow:0 5px 20px rgba(0,0,0,.10);}
h1{color:#0d1b52;}
input{padding:12px;width:420px;border-radius:8px;border:1px solid #ccc;}
button{padding:12px 18px;background:#0066ff;color:white;border:none;border-radius:8px;cursor:pointer;margin:4px;}
table{width:100%;margin-top:25px;border-collapse:collapse;background:white;}
th{background:#0d1b52;color:white;padding:10px;text-align:left;}
td{padding:10px;border-bottom:1px solid #ddd;font-size:14px;vertical-align:top;}
a{color:#0066ff;font-weight:bold;text-decoration:none;}
.msg{margin-top:18px;font-weight:bold;color:#0d1b52;}
.paginacao{margin-top:20px;text-align:center;}
.paginacao button{background:#0d1b52;}
</style>
</head>

<body>
<div class="box">
<h1>📊 Painel PNCP Inteligente</h1>

<input id="termo" placeholder="Digite motorista, limpeza, medicamento">
<button onclick="buscar(1)">Buscar</button>

<div id="resultado"></div>
</div>

<script>
async function buscar(pagina){
    let termo = document.getElementById("termo").value;
    document.getElementById("resultado").innerHTML = "<p class='msg'>Buscando no PNCP...</p>";

    let resposta = await fetch("/buscar_pncp?termo=" + encodeURIComponent(termo) + "&pagina=" + pagina);
    let retorno = await resposta.json();

    let dados = retorno.resultados;
    let paginaAtual = retorno.pagina;

    if(dados.length == 0){
        document.getElementById("resultado").innerHTML = "<p class='msg'>Nenhum resultado encontrado.</p>";
        return;
    }

    let html = `<p class='msg'>Página ${paginaAtual} — ${dados.length} resultados encontrados.</p>`;

    html += `
    <table>
    <tr>
        <th>Órgão</th>
        <th>Objeto</th>
        <th>UF</th>
        <th>Modalidade</th>
        <th>Início Proposta</th>
        <th>Fim Proposta</th>
        <th>Valor Estimado</th>
        <th>Link</th>
    </tr>`;

    dados.forEach(item => {
        html += `
        <tr>
            <td>${item.orgao}</td>
            <td>${item.objeto}</td>
            <td>${item.uf}</td>
            <td>${item.modalidade}</td>
            <td>${item.inicio}</td>
            <td>${item.fim}</td>
            <td>${item.valor}</td>
            <td><a href="${item.link}" target="_blank">Abrir edital</a></td>
        </tr>`;
    });

    html += "</table>";
    html += "<div class='paginacao'>";

    if(paginaAtual > 1){
        html += `<button onclick="buscar(${paginaAtual - 1})">⬅ Anterior</button>`;
    }

    html += `<button>Página ${paginaAtual}</button>`;

    if(retorno.tem_proxima){
        html += `<button onclick="buscar(${paginaAtual + 1})">Próxima ➡</button>`;
    }

    html += "</div>";
    document.getElementById("resultado").innerHTML = html;
}
</script>
</body>
</html>
"""


def palavras_relacionadas(termo):
    base = termo.lower().strip()

    mapa = {
        "motorista": [
            "motorista", "motoristas", "condutor", "condutores",
            "condução", "conducao", "operador",
            "locação de veículos com motorista",
            "locacao de veiculos com motorista",
            "transporte com motorista"
        ],
        "limpeza": [
            "limpeza", "higienização", "higienizacao",
            "asseio", "conservação", "conservacao", "faxina"
        ],
        "medicamento": [
            "medicamento", "medicamentos", "remédio",
            "remedios", "farmacêutico", "farmaceutico"
        ],
        "engenharia": [
            "engenharia", "obra", "obras", "reforma",
            "manutenção predial", "manutencao predial", "construção", "construcao"
        ],
        "veiculo": [
            "veículo", "veículos", "veiculo", "veiculos",
            "automóvel", "automovel", "carro", "van",
            "ônibus", "onibus", "locação de veículos", "locacao de veiculos"
        ]
    }

    return mapa.get(base, [base])


def formatar_data(txt):
    if not txt:
        return "-"

    try:
        data = txt[:10]
        hora = txt[11:16]

        ano, mes, dia = data.split("-")

        if hora:
            return f"{dia}/{mes}/{ano} às {hora} horas"

        return f"{dia}/{mes}/{ano}"

    except:
        return txt


def moeda(valor):
    if valor in [None, "", "null"]:
        return "-"

    try:
        numero = float(valor)
        return "R$ {:,.2f}".format(numero).replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "-"


def montar_link(item):
    texto_item = json.dumps(item, ensure_ascii=False)

    match = re.search(r"(\d{14})-\d-(\d+)/(\d{4})", texto_item)

    if match:
        cnpj = match.group(1)
        sequencial = str(int(match.group(2)))
        ano = match.group(3)
        return f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}"

    cnpj = item.get("orgao_cnpj") or item.get("cnpj") or item.get("ni") or ""
    ano = item.get("anoCompra") or item.get("ano_compra") or item.get("ano") or ""
    sequencial = item.get("sequencialCompra") or item.get("sequencial_compra") or item.get("sequencial") or ""

    if cnpj and ano and sequencial:
        return f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{int(sequencial)}"

    return "https://pncp.gov.br/app/editais"


@app.get("/buscar_pncp")
def buscar_pncp(termo: str = "", pagina: int = 1):
    url = "https://pncp.gov.br/api/search/"
    relacionados = palavras_relacionadas(termo)

    resultados = []
    ids_vistos = set()
    paginas_para_buscar = pagina * 3

    for palavra in relacionados:
        for pagina_pncp in range(1, paginas_para_buscar + 1):
            params = {
                "q": palavra,
                "tipos_documento": "edital",
                "ordenacao": "-data",
                "pagina": pagina_pncp,
                "tam_pagina": 100,
                "status": "recebendo_proposta"
            }

            try:
                resposta = requests.get(url, params=params, timeout=60)
                resposta.raise_for_status()
                dados = resposta.json()
            except Exception:
                continue

            itens = dados.get("items", [])

            if not itens:
                break

            for item in itens:
                orgao = item.get("orgao_nome", "")
                objeto = item.get("description") or item.get("titulo") or item.get("objeto") or "-"
                uf = item.get("uf", "-")

                texto = (objeto + " " + orgao).lower()

                achou = False
                for palavra_relacionada in relacionados:
                    if palavra_relacionada.lower() in texto:
                        achou = True
                        break

                if not achou:
                    continue

                identificador = (
                    item.get("id")
                    or item.get("numeroControlePNCP")
                    or item.get("numero_controle_pncp")
                    or json.dumps(item, ensure_ascii=False)
                )

                if identificador in ids_vistos:
                    continue

                ids_vistos.add(identificador)

                modalidade = (
                    item.get("modalidade_licitacao_nome")
                    or item.get("modalidade_nome")
                    or item.get("modalidade")
                    or "-"
                )

                inicio = (
                    item.get("data_inicio_proposta")
                    or item.get("data_inicio_recebimento_propostas")
                    or item.get("data_inicio_vigencia")
                    or item.get("dataAberturaProposta")
                    or "-"
                )

                fim = (
                    item.get("data_fim_proposta")
                    or item.get("data_fim_recebimento_propostas")
                    or item.get("data_fim_vigencia")
                    or item.get("dataEncerramentoProposta")
                    or "-"
                )

                valor = (
                    item.get("valor_total_estimado")
                    or item.get("valorTotalEstimado")
                    or item.get("valor_global")
                    or item.get("valor")
                )

                resultados.append({
                    "orgao": orgao,
                    "objeto": objeto,
                    "uf": uf,
                    "modalidade": modalidade,
                    "inicio": formatar_data(inicio),
                    "fim": formatar_data(fim),
                    "valor": moeda(valor),
                    "link": montar_link(item)
                })

    inicio_pagina = (pagina - 1) * RESULTADOS_POR_PAGINA
    fim_pagina = inicio_pagina + RESULTADOS_POR_PAGINA

    return {
        "pagina": pagina,
        "resultados": resultados[inicio_pagina:fim_pagina],
        "tem_proxima": len(resultados) > fim_pagina
    }