import streamlit as st
import pdfplumber
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
# Fase 1 — expressões compostas (aplicadas primeiro)
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
    # Fase 1: expressões compostas
    for original, abrev in ABREV_DREM_COMPOSTOS:
        resultado = re.sub(re.escape(original), abrev, resultado)
    # Fase 2: palavras individuais (só se ainda > 200)
    if len(resultado) > 200:
        for palavra, abrev in ABREV_DREM_INDIVIDUAIS.items():
            resultado = re.sub(r'\b' + re.escape(palavra) + r'\b', abrev, resultado)
    if len(resultado) > 200:
        resultado = resultado[:200]
    return resultado


def aplicar_abreviacoes_open(nome):
    resultado = nome.upper()
    if len(resultado) <= 200:
        return resultado
    for palavra, abrev in ABREV_OPEN.items():
        resultado = re.sub(r'\b' + re.escape(palavra) + r'\b', abrev, resultado)
    if len(resultado) > 200:
        resultado = resultado[:200]
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
    codigo = re.split(r"[\/\n]", codigo_raw)[0]
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
        modelo = item['modelo'].rstrip(".,") + sufixo
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


def criar_zip(xml_virgula, xml_ponto, prefixo):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zipf:
        zipf.writestr(f"{prefixo}_virgula.xml", xml_virgula.encode("ISO-8859-1", errors="replace"))
        zipf.writestr(f"{prefixo}_ponto.xml", xml_ponto.encode("ISO-8859-1", errors="replace"))
    buf.seek(0)
    return buf


# ─────────────────────────────────────────────
# PARSER PDF (Modo Open)
# ─────────────────────────────────────────────

def parse_pdf(pdf_path):
    rows = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for row in table:
                    if not row or len(row) < 6:
                        continue
                    ordem = clean(row[1])
                    if not re.fullmatch(r"\d{3}", ordem):
                        continue
                    ordem = int(ordem)
                    marca = clean(corrigir_texto(row[2]))
                    modelo = clean(corrigir_texto(row[3]))
                    nome = clean(corrigir_texto(row[4]))
                    codigo_raw = clean(corrigir_texto(row[5]))
                    codigo = extrair_codigo_unico(codigo_raw)
                    if not codigo:
                        continue
                    rows.append({
                        'ordem': ordem,
                        'marca': marca,
                        'modelo': modelo,
                        'nome': nome,
                        'codigo': codigo
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
    st.caption("Adicione os itens manualmente e gere o XML com as regras INNAC.")

    if "itens_drem" not in st.session_state:
        st.session_state.itens_drem = []

    with st.form("form_adicionar", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            marca = st.text_input("Marca", placeholder="Ex: INTELBRAS")
            modelo = st.text_input("Modelo", placeholder="Ex: IWA 3001")
        with col2:
            nome = st.text_input("Nome do Produto", placeholder="Ex: PONTO DE ACESSO WIRELESS")
            codigo = st.text_input("Código de Barras", placeholder="Ex: 12345678901234")

        adicionar = st.form_submit_button("➕ Adicionar Item", use_container_width=True)

    if adicionar:
        if marca and modelo and nome and codigo:
            codigo_limpo = extrair_codigo_unico(codigo)
            if codigo_limpo:
                st.session_state.itens_drem.append({
                    'marca': marca.upper().strip(),
                    'modelo': modelo.upper().strip(),
                    'nome': nome.upper().strip(),
                    'codigo': codigo_limpo
                })
                st.success(f"Item adicionado! Total: {len(st.session_state.itens_drem)}")
            else:
                st.error("Código inválido. Deve conter entre 8 e 14 dígitos numéricos.")
        else:
            st.warning("Preencha todos os campos antes de adicionar.")

    if st.session_state.itens_drem:
        st.markdown(f"**{len(st.session_state.itens_drem)} item(s) na lista:**")

        df_preview = pd.DataFrame(st.session_state.itens_drem)
        df_preview.index = range(1, len(df_preview) + 1)
        st.dataframe(
            df_preview[['marca', 'modelo', 'nome', 'codigo']],
            use_container_width=True,
            column_config={
                "marca": "Marca",
                "modelo": "Modelo",
                "nome": "Nome",
                "codigo": "Código"
            }
        )

        col_limpar, col_gerar = st.columns([1, 2])

        with col_limpar:
            if st.button("🗑️ Limpar Lista", use_container_width=True):
                st.session_state.itens_drem = []
                st.rerun()

        with col_gerar:
            if st.button("🚀 Gerar XML", type="primary", use_container_width=True):
                xml_virgula = gerar_xml(st.session_state.itens_drem, ",", aplicar_abreviacoes_drem)
                xml_ponto   = gerar_xml(st.session_state.itens_drem, ".", aplicar_abreviacoes_drem)
                zip_buf = criar_zip(xml_virgula, xml_ponto, "drem")

                st.download_button(
                    "📥 Baixar XMLs (ZIP)",
                    zip_buf,
                    "drem_xmls.zip",
                    mime="application/zip",
                    use_container_width=True
                )
    else:
        st.info("Nenhum item adicionado ainda. Use o formulário acima para começar.")


# ─── MODO 2: PDF > XML (OPEN) ────────────────────────────────────────────────

else:
    st.subheader("📄 PDF → XML — Certificados Open")
    st.caption("Envie o PDF e o sistema extrairá e converterá os dados automaticamente.")

    uploaded_file = st.file_uploader("Envie o PDF do certificado", type="pdf")

    if uploaded_file:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / uploaded_file.name
            pdf_path.write_bytes(uploaded_file.read())

            with st.spinner("Lendo e processando o PDF..."):
                rows = parse_pdf(pdf_path)

            if not rows:
                st.error("Nenhum item válido encontrado no PDF. Verifique se o formato está correto.")
                st.stop()

            df = pd.DataFrame(rows)
            df_exibir = df[['ordem', 'marca', 'modelo', 'nome', 'codigo']].copy()
            df_exibir.columns = ['Ordem', 'Marca', 'Modelo', 'Nome', 'Código']

            st.success(f"{len(rows)} item(s) encontrado(s) ✅")
            st.dataframe(df_exibir, use_container_width=True)

            xml_virgula = gerar_xml(rows, ",", aplicar_abreviacoes_open)
            xml_ponto   = gerar_xml(rows, ".", aplicar_abreviacoes_open)
            zip_buf = criar_zip(xml_virgula, xml_ponto, "open")

            st.download_button(
                "📥 Baixar XMLs (ZIP)",
                zip_buf,
                "open_xmls.zip",
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
            resultado = aplicar_abreviacoes_drem(descricao_input.strip())
            dict_label = "Drem (INNAC)"
        else:
            resultado = aplicar_abreviacoes_open(descricao_input.strip())
            dict_label = "Open"

        original_len = len(descricao_input.strip())
        resultado_len = len(resultado)
        abreviou = resultado_len < original_len

        st.markdown(f"**Resultado — dicionário {dict_label}:**")
        st.code(resultado, language=None)

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Original", f"{original_len} chars")
        col_b.metric("Resultado", f"{resultado_len} chars")
        col_c.metric("Redução", f"{original_len - resultado_len} chars" if abreviou else "—")

        if not abreviou and original_len <= 200:
            st.info("Descrição com 200 caracteres ou menos — abreviações não aplicadas.")
    else:
        st.warning("Cole uma descrição antes de abreviar.")
