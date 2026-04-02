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
    texto = fix_text(str(texto))

    for _ in range(3):
        original = texto
        try:
            texto = texto.encode("latin1").decode("utf-8")
        except:
            pass
        try:
            texto = texto.encode("cp1252").decode("utf-8")
        except:
            pass
        texto = fix_text(texto)
        if texto == original:
            break

    return texto


def limpar_iso(texto):
    if texto is None:
        return ""
    return texto.encode("ISO-8859-1", errors="ignore").decode("ISO-8859-1")


def limpar_final(texto):
    if texto is None:
        return ""
    return texto.replace("'", "").replace('"', "")


def escape_xml(texto):
    if texto is None:
        return ""
    texto = str(texto)
    texto = texto.replace("&", "&amp;")
    texto = texto.replace("<", "&lt;")
    texto = texto.replace(">", "&gt;")
    return texto


def limitar(nome):
    nome = clean(nome)
    if len(nome) > 200:
        nome = nome[:200]
    return nome


def is_item_row_table(row):
    if not row or len(row) < 6:
        return False
    ordem = clean(row[1])
    return bool(re.fullmatch(r"\d{3}", ordem))


def validar_codigo(codigo, ordem):
    codigo = re.sub(r"\D", "", codigo)

    if not codigo or not codigo.isdigit():
        erros.append(f"Item {ordem} ignorado: código inválido ({codigo})")
        return None

    if len(codigo) < 8 or len(codigo) > 14:
        erros.append(f"Item {ordem} ignorado: tamanho inválido ({codigo})")
        return None

    return codigo


def parse_pdf(pdf_path):
    rows = []
    seen = set()

    # 🔹 TABELA (PRINCIPAL)
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for row in table:
                    if not is_item_row_table(row):
                        continue

                    ordem = int(clean(row[1]))
                    marca = clean(corrigir_texto(row[2]))
                    modelo = clean(corrigir_texto(row[3]))
                    descricao = clean(corrigir_texto(row[4]))
                    codigo = clean(corrigir_texto(row[5]))

                    codigo = validar_codigo(codigo, ordem)
                    if not codigo:
                        continue

                    if not marca or not modelo or not descricao:
                        erros.append(f"Item {ordem} ignorado: campo vazio")
                        continue

                    key = (ordem, modelo, codigo)
                    if key in seen:
                        continue
                    seen.add(key)

                    rows.append([ordem, marca, modelo, descricao, codigo])

    if rows:
        rows.sort(key=lambda x: x[0])
        return rows

    # 🔹 FALLBACK
    doc = fitz.open(str(pdf_path))

    for page in doc:
        text = page.get_text("text")
        lines = [clean(corrigir_texto(line)) for line in text.splitlines() if clean(line)]

        for line in lines:
            m = re.match(r"^(\d{3})\s+(.+)$", line)
            if not m:
                continue

            ordem = int(m.group(1))
            conteudo = m.group(2)

            partes = conteudo.split()
            if len(partes) < 5:
                erros.append(f"Item {ordem} ignorado: estrutura inválida")
                continue

            marca = partes[0]
            modelo = partes[1]
            codigo = partes[-1]
            descricao = " ".join(partes[2:-1])

            codigo = validar_codigo(codigo, ordem)
            if not codigo:
                continue

            if not marca or not modelo or not descricao:
                erros.append(f"Item {ordem} ignorado: campo vazio")
                continue

            rows.append([ordem, marca, modelo, descricao, codigo])

    rows.sort(key=lambda x: x[0])
    return rows


if uploaded_file:
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / uploaded_file.name
        pdf_path.write_bytes(uploaded_file.read())

        rows = parse_pdf(pdf_path)

        if not rows:
            st.error("Nenhum item válido foi encontrado no PDF.")
            st.stop()

        df = pd.DataFrame(rows, columns=["ORDEM", "MARCA", "MODELO", "DESC", "CODIGO"])

        def gerar(df, suf):
            linhas = [
                '<?xml version="1.0" encoding="ISO-8859-1"?>',
                '<ArrayOfItemSolicitacao>'
            ]

            for _, r in df.iterrows():
                linhas.extend([
                    "<ItemSolicitacao>",
                    f"<Marca>{escape_xml(limpar_iso(limpar_final(r['MARCA'])))}</Marca>",
                    f"<Modelo>{escape_xml(limpar_iso(limpar_final(clean(r['MODELO']) + suf)))}</Modelo>",
                    f"<Nome>{escape_xml(limpar_iso(limpar_final(limitar(r['DESC']))))}</Nome>",
                    "<CodigosBarras>",
                    f"<Codigo>{escape_xml(limpar_iso(limpar_final(r['CODIGO'])))}</Codigo>",
                    "</CodigosBarras>",
                    "</ItemSolicitacao>"
                ])

            linhas.append("</ArrayOfItemSolicitacao>")
            return "\n".join(linhas).strip()

        xml_comma = gerar(df, ",")
        xml_dot = gerar(df, ".")

        zip_path = Path(tmpdir) / "resultado_final.zip"

        with zipfile.ZipFile(zip_path, "w") as zipf:
            zipf.writestr("xml_comma.xml", xml_comma)
            zipf.writestr("xml_dot.xml", xml_dot)

        st.success("Processado com sucesso!")

        if erros:
            st.warning("Itens ignorados automaticamente:")
            for e in erros[:10]:
                st.write(e)

        with open(zip_path, "rb") as f:
            st.download_button("Baixar ZIP", f, "resultado_final.zip")
