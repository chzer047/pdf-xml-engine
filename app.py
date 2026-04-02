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


# 🔥 FUNÇÃO CRÍTICA (1 CÓDIGO POR ITEM)
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


def is_item_row_table(row):
    if not row or len(row) < 6:
        return False
    ordem = clean(row[1])
    return bool(re.fullmatch(r"\d{3}", ordem))


def parse_pdf(pdf_path):
    rows = []
    seen = set()

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

                    codigo_raw = clean(corrigir_texto(row[5]))
                    codigo = extrair_codigo_unico(codigo_raw)

                    if not codigo:
                        erros.append(f"Item {ordem} ignorado: código inválido ({codigo_raw})")
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

    # fallback PyMuPDF
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
            codigo_raw = partes[-1]
            descricao = " ".join(partes[2:-1])

            codigo = extrair_codigo_unico(codigo_raw)

            if not codigo:
                erros.append(f"Item {ordem} ignorado: código inválido ({codigo_raw})")
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

        st.success("Excel gerado no padrão do seu GPT ✅")

        st.dataframe(df)

        if erros:
            st.warning("Itens ignorados automaticamente:")
            for e in erros[:10]:
                st.write(e)
