import streamlit as st
import pdfplumber
import fitz
import re
import pandas as pd
from pathlib import Path
import zipfile
import tempfile
from ftfy import fix_text

st.title("C XML BR Engine - PDF → XML")

uploaded_file = st.file_uploader("Envie o PDF", type="pdf")

erros = []


def clean(x):
    if x is None:
        return ""
    return re.sub(r"\s+", " ", str(x).replace("\n", " ")).strip()


def corrigir_texto(texto):
    if texto is None:
        return ""
    return fix_text(str(texto))


# 🔥 REGRA: 1 CÓDIGO POR ITEM
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


def limitar_nome(nome):
    nome = clean(nome)

    if len(nome) > 200:
        nome = nome.replace("PRODUZIDO", "PROD.")
        nome = nome.replace("INDICATIVO", "IND.")
        nome = nome.replace("RESTRITIVO", "REST.")
        nome = nome[:200]

    return nome


def escape_xml(texto):
    return str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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

                    rows.append([ordem, marca, modelo, nome, codigo])

    rows.sort(key=lambda x: x[0])
    return rows


if uploaded_file:
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / uploaded_file.name
        pdf_path.write_bytes(uploaded_file.read())

        rows = parse_pdf(pdf_path)

        if not rows:
            st.error("Nenhum item válido encontrado")
            st.stop()

        df = pd.DataFrame(rows, columns=["ORDEM", "MARCA", "MODELO", "NOME", "CODIGO"])

        st.success("Excel gerado no padrão do seu GPT ✅")
        st.dataframe(df)

        # 🔥 GERADOR XML (PADRÃO GPT)
        def gerar_xml(df, sufixo):
            linhas = [
                '<?xml version="1.0" encoding="ISO-8859-1"?>',
                '<ArrayOfItemSolicitacao>'
            ]

            for _, r in df.iterrows():
                modelo = r["MODELO"].rstrip(".,") + sufixo

                linhas.append(f"""
<ItemSolicitacao>
<Marca>{escape_xml(r['MARCA'])}</Marca>
<Modelo>{escape_xml(modelo)}</Modelo>
<Nome>{escape_xml(limitar_nome(r['NOME']))}</Nome>
<CodigosBarras>
<Codigo>{r['CODIGO']}</Codigo>
</CodigosBarras>
</ItemSolicitacao>
""")

            linhas.append("</ArrayOfItemSolicitacao>")
            return "\n".join(linhas)

        xml_comma = gerar_xml(df, ",")
        xml_dot = gerar_xml(df, ".")

        zip_path = Path(tmpdir) / "resultado_xml.zip"

        with zipfile.ZipFile(zip_path, "w") as zipf:
            # 🔥 CONVERSÃO REAL PARA ISO-8859-1
            zipf.writestr("xml_virgula.xml", xml_comma.encode("ISO-8859-1", errors="replace"))
            zipf.writestr("xml_ponto.xml", xml_dot.encode("ISO-8859-1", errors="replace"))

        with open(zip_path, "rb") as f:
            st.download_button("Baixar XMLs", f, "resultado_xml.zip")
