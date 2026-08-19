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

# Modo 1: XML Rápido — Certificados Drem
ABREV_DREM = {
    "PRODUZIDO": "PROD.",
    "INDICATIVO": "IND.",
    "RESTRITIVO": "REST.",
    "CERTIFICADO": "CERT.",
    "CERTIFICAÇÃO": "CERT.",
    "HOMOLOGADO": "HOMOL.",
    "HOMOLOGAÇÃO": "HOMOL.",
    "APROVADO": "APROV.",
    "EQUIPAMENTO": "EQUIP.",
    "DISPOSITIVO": "DISP.",
    "COMPONENTE": "COMP.",
    "MÓDULO": "MOD.",
    "SISTEMA": "SIST.",
    "FREQUÊNCIA": "FREQ.",
    "TRANSMISSOR": "TRANS.",
    "RECEPTOR": "RECEPT.",
    "AMPLIFICADOR": "AMP.",
    "CONTROLADOR": "CTRL.",
    "PROCESSADOR": "PROC.",
    "INTERFACE": "INTERF.",
    "ADAPTADOR": "ADAPT.",
    "CONVERSOR": "CONV.",
    "CARREGADOR": "CARR.",
    "ALIMENTAÇÃO": "ALIM.",
    "INDUSTRIAL": "IND.",
    "RESIDENCIAL": "RESID.",
    "COMERCIAL": "COM.",
    "PORTÁTIL": "PORT.",
    "DIGITAL": "DIG.",
    "ANALÓGICO": "ANAL.",
    "BLUETOOTH": "BT.",
    "WIRELESS": "WLS.",
    "ETHERNET": "ETH.",
}

# Modo 2: PDF>XML — Certificados Open
ABREV_OPEN = {
    "PRODUZIDO": "PROD.",
    "INDICATIVO": "IND.",
    "RESTRITIVO": "REST.",
    "CERTIFICADO": "CERT.",
    "CERTIFICAÇÃO": "CERT.",
    "HOMOLOGADO": "HOMOL.",
    "HOMOLOGAÇÃO": "HOMOL.",
    "APROVADO": "APROV.",
    "EQUIPAMENTO": "EQUIP.",
    "DISPOSITIVO": "DISP.",
    "COMPONENTE": "COMP.",
    "MÓDULO": "MOD.",
    "SISTEMA": "SIST.",
    "FREQUÊNCIA": "FREQ.",
    "TRANSMISSOR": "TRANS.",
    "RECEPTOR": "RECEPT.",
    "AMPLIFICADOR": "AMP.",
    "CONTROLADOR": "CTRL.",
    "PROCESSADOR": "PROC.",
    "INTERFACE": "INTERF.",
    "ADAPTADOR": "ADAPT.",
    "INDUSTRIAL": "INDUSTR.",
    "RESIDENCIAL": "RESID.",
    "COMERCIAL": "COMERC.",
    "MICROCOMPUTADOR": "MICROCOMP.",
    "COMPUTADOR": "COMPUT.",
    "IMPRESSORA": "IMPR.",
    "MONITOR": "MONIT.",
    "TECLADO": "TECL.",
    "TABLET": "TABL.",
    "SMARTPHONE": "SMRTPH.",
    "CELULAR": "CEL.",
    "TELEFONE": "TEL.",
    "ROTEADOR": "RTDR.",
    "MODEM": "MDM.",
    "NOTEBOOK": "NTB.",
    "PORTÁTIL": "PORT.",
    "DIGITAL": "DIG.",
    "ANALÓGICO": "ANAL.",
    "BLUETOOTH": "BT.",
    "WIRELESS": "WLS.",
    "ETHERNET": "ETH.",
    "CONVERSOR": "CONV.",
    "CARREGADOR": "CARR.",
    "ALIMENTAÇÃO": "ALIM.",
}

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


def aplicar_abreviacoes(nome, dicionario):
    resultado = nome.upper()
    for palavra, abrev in dicionario.items():
        resultado = re.sub(r'\b' + re.escape(palavra) + r'\b', abrev, resultado)
    if len(resultado) > 200:
        resultado = resultado[:200]
    return resultado


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


def gerar_xml(items, sufixo, dicionario):
    linhas = [
        '<?xml version="1.0" encoding="ISO-8859-1"?>',
        '<ArrayOfItemSolicitacao>'
    ]
    for item in items:
        modelo = item['modelo'].rstrip(".,") + sufixo
        nome = aplicar_abreviacoes(clean(item['nome']), dicionario)
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
    st.caption("Adicione os itens manualmente e gere o XML com as regras Drem.")

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
                xml_virgula = gerar_xml(st.session_state.itens_drem, ",", ABREV_DREM)
                xml_ponto = gerar_xml(st.session_state.itens_drem, ".", ABREV_DREM)
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

            xml_virgula = gerar_xml(rows, ",", ABREV_OPEN)
            xml_ponto = gerar_xml(rows, ".", ABREV_OPEN)
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
