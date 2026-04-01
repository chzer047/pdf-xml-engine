import streamlit as st
import pdfplumber
import re
import pandas as pd
from pathlib import Path
import zipfile
import tempfile

st.title("C XML BR Engine - PDF → XML")

uploaded_file = st.file_uploader("Envie o PDF", type="pdf")

def clean(x):
    if x is None:
        return ""
    return re.sub(r"\s+", " ", str(x).replace("\n"," ")).strip()

def corrigir_texto(texto):
    if texto is None:
        return ""
    try:
        return texto.encode('latin1').decode('utf-8')
    except:
        return texto

def is_item(row):
    if not row or len(row) < 6:
        return False
    return re.fullmatch(r"\d{3}", clean(row[1])) is not None

def limpar_iso(texto):
    if texto is None:
        return ""
    return texto.encode("ISO-8859-1", errors="ignore").decode("ISO-8859-1")

def escape_xml(texto):
    if texto is None:
        return ""
    texto = str(texto)
    texto = texto.replace("&", "&amp;")
    texto = texto.replace("<", "&lt;")
    texto = texto.replace(">", "&gt;")
    texto = texto.replace('"', "&quot;")
    texto = texto.replace("'", "&apos;")
    return texto

if uploaded_file:
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "input.pdf"
        pdf_path.write_bytes(uploaded_file.read())

        rows = []
        seen = set()

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    for row in table:
                        if not is_item(row):
                            continue

                        ordem = int(clean(row[1]))
                        marca = corrigir_texto(clean(row[2]))
                        modelo = corrigir_texto(clean(row[3]))
                        descricao = corrigir_texto(clean(row[4]))
                        codigo = clean(row[5]).replace(" ", "")

                        key = (ordem, modelo)
                        if key in seen:
                            continue
                        seen.add(key)

                        rows.append([ordem, marca, modelo, descricao, codigo])

        rows.sort(key=lambda x: x[0])

        df = pd.DataFrame(rows, columns=["ORDEM","MARCA","MODELO","DESC","CODIGO"])

        def limitar(nome):
            nome = clean(nome)
            if len(nome) <= 200:
                return nome
            return nome[:200]

        def gerar(df, suf):
            linhas = [
                '<?xml version="1.0" encoding="ISO-8859-1"?>',
                '<ArrayOfItemSolicitacao>'
            ]

            for _, r in df.iterrows():
                linhas.extend([
                    "<ItemSolicitacao>",
                    f"<Marca>{escape_xml(limpar_iso(r['MARCA']))}</Marca>",
                    f"<Modelo>{escape_xml(limpar_iso(clean(r['MODELO'])+suf))}</Modelo>",
                    f"<Nome>{escape_xml(limpar_iso(limitar(r['DESC'])))}</Nome>",
                    "<CodigosBarras>",
                    f"<Codigo>{escape_xml(limpar_iso(r['CODIGO']))}</Codigo>",
                    "</CodigosBarras>",
                    "</ItemSolicitacao>"
                ])

            linhas.append("</ArrayOfItemSolicitacao>")

            return "\n".join(linhas).strip()

        xml1 = gerar(df, ",")
        xml2 = gerar(df, ".")

        zip_path = Path(tmpdir) / "resultado.zip"

        with zipfile.ZipFile(zip_path, 'w') as zipf:
            zipf.writestr("xml_comma.xml", xml1)
            zipf.writestr("xml_dot.xml", xml2)

        st.success("Processado com sucesso!")
        with open(zip_path, "rb") as f:
            st.download_button("Baixar ZIP", f, "resultado.zip")
