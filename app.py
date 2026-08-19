import streamlit as st
import pdfplumber
import fitz
import re
import pandas as pd
from pathlib import Path
import zipfile
import tempfile
from ftfy import fix_text
import io

st.set_page_config(
    page_title="C XML Engine",
    page_icon="📄",
    layout="wide"
)

# ─────────────────────────────────────────────
# DICIONÁRIOS DE ABREVIAÇÕES
# ─────────────────────────────────────────────

# Modo 1: XML Rápido — Certificados Drem (INNAC)
# Regra: só aplica se nome > 200 chars
# Fase 1 — expressões compostas (aplicadas primeiro, na ordem exata)
ABREV_DREM_COMPOSTOS = [
    ("REVESTIMENTO EXTERNO",            "REV.EXT."),
    ("DETALHES EM TECIDO BORDADO",      "DET.BORD."),
    ("FAIXA ETARIA INDICATIVA",         "F.IND."),
    ("FAIXA ETARIA RESTRITIVA",         "F.REST."),
    ("COSTURA INDUSTRIAL",              "CST.IND."),
    ("COSTURA INVISÍVEL",               "CST.INV."),
    ("COSTURA INVISIVEL",               "CST.INV."),
    ("FIXAÇÃO DE COMPONENTES",          "FIX.COMP."),
    ("FIXACAO DE COMPONENTES",          "FIX.COMP."),
    ("PONTO ESCADA",                    "PT.ESC."),
    ("TECIDO E METAL",                  "TEC.MET."),
]

# Fase 2 — palavras individuais (só se ainda > 200 após fase 1)
ABREV_DREM_INDIVIDUAIS = {
    "ENCHIMENTO":   "ENCH.",
    "REVESTIMENTO": "REVEST.",
    "FAIXA ETARIA": "F.ET.",
    "INDICATIVA":   "INDIC.",
    "RESTRITIVA":   "RESTR.",
    "INDUSTRIAL":   "IND.",
    "INVISÍVEL":    "INVIS.",
    "INVISIVEL":    "INVIS.",
    "COMPONENTES":  "COMP.",
    "EXTERNO":      "EXT.",
    "BORDADO":      "BORD.",
    "COSTURA":      "COST.",
    "FIXAÇÃO":      "FIX.",
    "FIXACAO":      "FIX.",
    "TECIDO":       "TEC.",
}

# Modo 2: PDF>XML — Certificados Open
# Regra: só aplica se nome > 200 chars
ABREV_OPEN = {
    "PRODUZIDO":  "PROD.",
    "INDICATIVO": "IND.",
    "RESTRITIVO": "REST.",
    "ANOS":       "A",
    "MESES":      "MES.",
    "INJEÇÃO":    "INJ.",
    "INJECAO":    "INJ.",
    "MÁXIMA":     "MAX.",
    "MAXIMA":     "MAX.",
    "PLÁSTICO":   "PLAST.",
    "PLASTICO":   "PLAST.",
    "CONTROLE":   "CONT.",
    "REMOTO":     "REM.",
    "VELOCIDADE": "VEL.",
    "MEDIDAS":    "MED.",
}

# ─────────────────────────────────────────────
# FUNÇÕES DE ABREVIAÇÃO
# ─────────────────────────────────────────────

def aplicar_abreviacoes_drem(nome):
    resultado = nome.upper()
    if len(resultado) <= 200:
        return resultado
    for original, abrev in ABREV_DREM_COMPOSTOS:
        resultado = re.sub(re.escape(original), abrev, resultado)
    if len(resultado) > 200:
        for palavra, abrev in ABREV_DREM_INDIVIDUAIS.items():
            resultado = re.sub(r'\b' + re.escape(palavra) + r'\b', abrev, resultado)
    if len(resultado) > 200:
        resultado = resultado[:200].rstrip(", ;")
    return resultado


def aplicar_abreviacoes_open(nome):
    resultado = nome.upper()
    if len(resultado) <= 200:
        return resultado
    for palavra, abrev in ABREV_OPEN.items():
        resultado = re.sub(r'\b' + re.escape(palavra) + r'\b', abrev, resultado)
    if len(resultado) > 200:
        resultado = resultado[:200].rstrip(", ;")
    return resultado


# ─────────────────────────────────────────────
# FUNÇÕES UTILITÁRIAS
# ─────────────────────────────────────────────

def clean(x):
    if x is None:
        return ""
    return re.sub(r"\s+", " ", str(x).replace("\n", " ")).strip()


def corrigir_texto(texto):
    if texto is None:
        return ""
    return fix_text(str(texto))


def escape_xml(texto):
    return str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def extrair_codigo_unico(codigo_raw):
    if not codigo_raw:
        return None
    codigo = re.split(r"[\/\n]", str(codigo_raw))[0]
    codigo = re.sub(r"\D", "", codigo)
    if not codigo or not codigo.isdigit():
        return None
    if len(codigo) < 8 or len(codigo) > 14:
        return None
    return codigo


def gerar_xml(items, sufixo, fn_abrev):
    linhas = [
        '<?xml version="1.0" encoding="ISO-8859-1"?>',
        '<ArrayOfItemSolicitacao>'
    ]
    for item in items:
        modelo = item['modelo'].rstrip(".,")
        if sufixo:
            modelo += sufixo
        nome = fn_abrev(clean(item['nome']))
        linhas.append(f"""
<ItemSolicitacao>
<Marca>{escape_xml(item['marca'])}</Marca>
<Modelo>{escape_xml(modelo)}</Modelo>
<Nome>{escape_xml(nome)}</Nome>
<CodigosBarras>
<Codigo>{item['codigo']}</Codigo>
</CodigosBarras>
</ItemSolicitacao>
""")
    linhas.append("</ArrayOfItemSolicitacao>")
    return "\n".join(linhas)


def criar_zip_tres(xml_virgula, xml_ponto, xml_sem, prefixo):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zipf:
        zipf.writestr(f"{prefixo}_virgula.xml", xml_virgula.encode("ISO-8859-1", errors="replace"))
        zipf.writestr(f"{prefixo}_ponto.xml",   xml_ponto.encode("ISO-8859-1",   errors="replace"))
        zipf.writestr(f"{prefixo}_sem.xml",     xml_sem.encode("ISO-8859-1",     errors="replace"))
    buf.seek(0)
    return buf


# ─────────────────────────────────────────────
# PARSER INNAC — fitz (XML Rápido / Drem)
# ─────────────────────────────────────────────

def extrair_header_innac(pdf_path):
    doc = fitz.open(str(pdf_path))
    texto = doc[0].get_text() if len(doc) > 0 else ""
    doc.close()

    ip_bri = re.search(r'IP-BRI[-\s]*([\w/\-\.]+)', texto)
    ce_bri = re.search(r'CE-BRI[/\-\s]*([\w/\-\.]+)', texto)
    data   = re.search(r'(\d{2}/\d{2}/\d{4})', texto)
    rev    = re.search(r'\bREV\.?\s*(\w+)', texto, re.IGNORECASE)
    qty    = re.search(r'(\d+)\s*(?:produtos?\s*declarados?|itens?\s*declarados?)', texto, re.IGNORECASE)

    return {
        'ip_bri':        ip_bri.group(0) if ip_bri else None,
        'ce_bri':        ce_bri.group(0) if ce_bri else None,
        'data':          data.group(1) if data else None,
        'rev':           rev.group(1) if rev else None,
        'qty_declarada': int(qty.group(1)) if qty else None,
    }


def parse_pdf_innac(pdf_path):
    rows = []
    ultimo_valido = None

    doc = fitz.open(str(pdf_path))
    for page in doc:
        tabs = page.find_tables()
        for tab in tabs:
            for row in tab.extract():
                if not row or len(row) < 6:
                    continue

                col1 = clean(str(row[1])) if row[1] is not None else ""
                col2 = clean(corrigir_texto(str(row[2]))) if row[2] is not None else ""
                col3 = clean(corrigir_texto(str(row[3]))) if row[3] is not None else ""
                col4 = clean(corrigir_texto(str(row[4]).replace('\n', ' '))) if row[4] is not None else ""
                col5 = clean(corrigir_texto(str(row[5]))) if row[5] is not None else ""

                if re.fullmatch(r'\d{1,4}', col1):
                    codigo = extrair_codigo_unico(col5)
                    if not codigo or not col3:
                        continue
                    item = {
                        'ordem':  int(col1),
                        'marca':  col2,
                        'modelo': col3,
                        'nome':   col4,
                        'codigo': codigo,
                    }
                    rows.append(item)
                    ultimo_valido = item

                elif not col1 and not col2 and not col3 and col4 and ultimo_valido is not None:
                    ultimo_valido['nome'] = (ultimo_valido['nome'] + ' ' + col4).strip()

    doc.close()

    rows.sort(key=lambda x: x['ordem'])

    seen = set()
    unique = []
    for r in rows:
        if r['codigo'] not in seen:
            seen.add(r['codigo'])
            unique.append(r)

    return unique


# ─────────────────────────────────────────────
# PARSER OPEN — pdfplumber (PDF→XML)
# ─────────────────────────────────────────────

def extrair_header_open(pdf_path):
    doc = fitz.open(str(pdf_path))
    texto = "".join(page.get_text() for page in doc)
    doc.close()

    ip_bri = re.search(r'IP-BRI[-\s]*([\w/\-\.]+)', texto)
    ce_bri = re.search(r'CE-BRI[/\-\s]*([\w/\-\.]+)', texto)
    data   = re.search(r'(\d{2}/\d{2}/\d{4})', texto)
    rev    = re.search(r'\bREV\.?\s*(\w+)', texto, re.IGNORECASE)

    return {
        'ip_bri': ip_bri.group(0) if ip_bri else None,
        'ce_bri': ce_bri.group(0) if ce_bri else None,
        'data':   data.group(1) if data else None,
        'rev':    rev.group(1) if rev else None,
    }


def parse_pdf_open(pdf_path):
    rows = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for row in table:
                    if not row or len(row) < 6:
                        continue
                    ordem = clean(row[1])
                    if not re.fullmatch(r"\d{3,4}", ordem):
                        continue
                    ordem      = int(ordem)
                    marca      = clean(corrigir_texto(row[2]))
                    modelo     = clean(corrigir_texto(row[3]))
                    nome       = clean(corrigir_texto(row[4]))
                    codigo_raw = clean(corrigir_texto(row[5]))
                    codigo     = extrair_codigo_unico(codigo_raw)
                    if not codigo:
                        continue
                    rows.append({
                        'ordem':  ordem,
                        'marca':  marca,
                        'modelo': modelo,
                        'nome':   nome,
                        'codigo': codigo,
                    })
    rows.sort(key=lambda x: x['ordem'])
    return rows


# ─────────────────────────────────────────────
# INTERFACE
# ─────────────────────────────────────────────

st.title("📄 C XML Engine")
st.markdown("---")

modo = st.radio(
    "**Selecione o modo:**",
    [
        "⚡ XML Rápido — Certificados Drem",
        "📄 PDF → XML — Certificados Open"
    ],
    horizontal=True
)

st.markdown("---")


# ─── MODO 1: XML RÁPIDO (DREM) ───────────────────────────────────────────────

if "XML Rápido" in modo:
    st.subheader("⚡ XML Rápido — Certificados Drem")
    st.caption("Envie um ou vários PDFs. Cada um é processado separadamente com as regras INNAC.")

    uploaded_files = st.file_uploader(
        "Envie os PDFs dos certificados Drem",
        type="pdf",
        accept_multiple_files=True,
        key="uploader_drem"
    )

    if uploaded_files:
        resultados = []

        for uploaded in uploaded_files:
            nome_base = Path(uploaded.name).stem
            st.markdown(f"---\n**📄 {uploaded.name}**")

            with tempfile.TemporaryDirectory() as tmpdir:
                pdf_path = Path(tmpdir) / uploaded.name
                pdf_path.write_bytes(uploaded.read())

                with st.spinner(f"Processando {uploaded.name}..."):
                    header = extrair_header_innac(pdf_path)
                    rows   = parse_pdf_innac(pdf_path)

            if not rows:
                st.error(f"Nenhum item válido encontrado em {uploaded.name}.")
                continue

            col_a, col_b, col_c, col_d = st.columns(4)
            col_a.metric("IP-BRI", header['ip_bri'] or "—")
            col_b.metric("CE-BRI", header['ce_bri'] or "—")
            col_c.metric("Data",   header['data']   or "—")
            col_d.metric("REV",    header['rev']    or "—")

            if header['qty_declarada'] and len(rows) != header['qty_declarada']:
                st.warning(f"Atenção: {len(rows)} itens extraídos, mas o PDF declara {header['qty_declarada']}.")

            codigos = [r['codigo'] for r in rows]
            duplicados = sorted(set(c for c in codigos if codigos.count(c) > 1))
            if duplicados:
                st.warning(f"Códigos duplicados detectados: {', '.join(duplicados)}")

            nomes_longos = sum(1 for r in rows if len(r['nome']) > 200)
            if nomes_longos:
                st.info(f"{nomes_longos} descrição(ões) com > 200 chars — abreviações INNAC serão aplicadas.")

            df = pd.DataFrame(rows)
            df.index = range(1, len(df) + 1)
            st.dataframe(
                df[['marca', 'modelo', 'nome', 'codigo']],
                use_container_width=True,
                column_config={"marca": "Marca", "modelo": "Modelo", "nome": "Nome", "codigo": "Código"}
            )
            st.success(f"{len(rows)} item(s) encontrado(s) ✅")

            xml_virgula = gerar_xml(rows, ",", aplicar_abreviacoes_drem)
            xml_ponto   = gerar_xml(rows, ".", aplicar_abreviacoes_drem)
            xml_sem     = gerar_xml(rows, "",  aplicar_abreviacoes_drem)
            zip_buf     = criar_zip_tres(xml_virgula, xml_ponto, xml_sem, nome_base)
            zip_bytes   = zip_buf.getvalue()
            resultados.append((nome_base, zip_bytes))

            st.download_button(
                f"📥 Baixar XMLs — {uploaded.name}",
                zip_bytes,
                f"{nome_base}_xmls.zip",
                mime="application/zip",
                use_container_width=True,
                key=f"dl_{nome_base}"
            )

        if len(resultados) > 1:
            st.markdown("---")
            master_buf = io.BytesIO()
            with zipfile.ZipFile(master_buf, "w") as zipf:
                for nome, zb in resultados:
                    zipf.writestr(f"{nome}_xmls.zip", zb)
            master_buf.seek(0)
            st.download_button(
                "📦 Baixar Todos (ZIP geral)",
                master_buf,
                "todos_xmls.zip",
                mime="application/zip",
                use_container_width=True,
                type="primary"
            )

    else:
        st.info("Aguardando o envio do(s) PDF(s).")


# ─── MODO 2: PDF → XML (OPEN) ────────────────────────────────────────────────

else:
    st.subheader("📄 PDF → XML — Certificados Open")
    st.caption("Envie o PDF e o sistema extrairá e converterá os dados automaticamente.")

    uploaded_file = st.file_uploader(
        "Envie o PDF do certificado",
        type="pdf",
        key="uploader_open"
    )

    if uploaded_file:
        nome_base = Path(uploaded_file.name).stem

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / uploaded_file.name
            pdf_path.write_bytes(uploaded_file.read())

            with st.spinner("Lendo e processando o PDF..."):
                header = extrair_header_open(pdf_path)
                rows   = parse_pdf_open(pdf_path)

        if not rows:
            st.error("Nenhum item válido encontrado no PDF. Verifique se o formato está correto.")
            st.stop()

        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("IP-BRI", header['ip_bri'] or "—")
        col_b.metric("CE-BRI", header['ce_bri'] or "—")
        col_c.metric("Data",   header['data']   or "—")
        col_d.metric("REV",    header['rev']    or "—")

        codigos = [r['codigo'] for r in rows]
        duplicados = sorted(set(c for c in codigos if codigos.count(c) > 1))
        if duplicados:
            st.warning(f"Códigos duplicados detectados: {', '.join(duplicados)}")

        df = pd.DataFrame(rows)
        df_exibir = df[['ordem', 'marca', 'modelo', 'nome', 'codigo']].copy()
        df_exibir.columns = ['Ordem', 'Marca', 'Modelo', 'Nome', 'Código']

        st.success(f"{len(rows)} item(s) encontrado(s) ✅")
        st.dataframe(df_exibir, use_container_width=True)

        xml_virgula = gerar_xml(rows, ",", aplicar_abreviacoes_open)
        xml_ponto   = gerar_xml(rows, ".", aplicar_abreviacoes_open)
        xml_sem     = gerar_xml(rows, "",  aplicar_abreviacoes_open)
        zip_buf     = criar_zip_tres(xml_virgula, xml_ponto, xml_sem, nome_base)

        st.download_button(
            "📥 Baixar XMLs (ZIP)",
            zip_buf,
            f"{nome_base}_xmls.zip",
            mime="application/zip",
            use_container_width=True
        )

    else:
        st.info("Aguardando o envio do PDF.")


# ─── ABREVIADOR DE DESCRIÇÕES ────────────────────────────────────────────────

st.markdown("---")
st.subheader("✂️ Abreviador de Descrições")
st.caption("Cole uma descrição, escolha o dicionário e veja o resultado abreviado.")

col_input, col_config = st.columns([3, 1])

with col_config:
    dicionario_escolhido = st.selectbox(
        "Dicionário",
        ["⚡ Drem (INNAC)", "📄 Open"],
        key="abrev_dict"
    )

with col_input:
    descricao_input = st.text_area(
        "Descrição original",
        placeholder="Cole aqui a descrição do produto...",
        height=120,
        key="abrev_input"
    )

if st.button("✂️ Abreviar", type="primary", key="btn_abreviar"):
    if descricao_input.strip():
        if "Drem" in dicionario_escolhido:
            resultado  = aplicar_abreviacoes_drem(descricao_input.strip())
            dict_label = "Drem (INNAC)"
        else:
            resultado  = aplicar_abreviacoes_open(descricao_input.strip())
            dict_label = "Open"

        original_len  = len(descricao_input.strip())
        resultado_len = len(resultado)
        abreviou      = resultado_len < original_len

        st.markdown(f"**Resultado — dicionário {dict_label}:**")
        st.code(resultado, language=None)

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Original",  f"{original_len} chars")
        col_b.metric("Resultado", f"{resultado_len} chars")
        col_c.metric("Redução",   f"{original_len - resultado_len} chars" if abreviou else "—")

        if not abreviou and original_len <= 200:
            st.info("Descrição com 200 caracteres ou menos — abreviações não aplicadas.")
    else:
        st.warning("Cole uma descrição antes de abreviar.")
