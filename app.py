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


def limitar(nome):
    nome = clean(nome)
    if len(nome) <= 200:
        return nome
    return nome[:200]


def is_item_row_table(row):
    if not row or len(row) < 6:
        return False
    ordem = clean(row[1])
    return bool(re.fullmatch(r"\d{3}", ordem))


def parse_with_pdfplumber_tables(pdf_path: Path):
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
                    codigo = clean(corrigir_texto(row[5])).replace(" ", "").replace("*", "")

                    if not codigo:
                        continue

                    key = (ordem, marca, modelo, codigo)
                    if key in seen:
                        continue
                    seen.add(key)

                    rows.append([ordem, marca, modelo, descricao, codigo])

    rows.sort(key=lambda x: x[0])
    return rows


def parse_with_pymupdf_fallback(pdf_path: Path):
    rows = []
    seen = set()

    doc = fitz.open(str(pdf_path))

    for page in doc:
        text = page.get_text("text")
        lines = [clean(corrigir_texto(line)) for line in text.splitlines() if clean(line)]

        i = 0
        while i < len(lines):
            line = lines[i]

            m = re.match(r"^(\d{3})\s+(.+)$", line)
            if not m:
                i += 1
                continue

            ordem = int(m.group(1))
            rest = m.group(2)

            if "Rol de Produtos" in rest or "Nome da Família" in rest:
                i += 1
                continue

            bloco = [rest]
            codigo = ""
            j = i + 1

            while j < len(lines):
                current = lines[j]

                if re.match(r"^\d{3}\s+.+$", current):
                    break

                bloco.append(current)

                if re.fullmatch(r"[\d\*\s]{8,}", current):
                    codigo = clean(current).replace(" ", "").replace("*", "")
                    j += 1
                    break

                j += 1

            if not codigo:
                i += 1
                continue

            full = " ".join(bloco[:-1]).strip() if len(bloco) > 1 else bloco[0]
            if " - " not in full:
                i = j
                continue

            left, right = full.split(" - ", 1)
            left_parts = left.split()
            if len(left_parts) < 2:
                i = j
                continue

            modelo_codigo = left_parts[-1]
            marca = " ".join(left_parts[:-1])
            modelo = f"{modelo_codigo} - {right}"
            descricao = right

            marca = clean(corrigir_texto(marca))
            modelo = clean(corrigir_texto(modelo))
            descricao = clean(corrigir_texto(descricao))
            codigo = clean(corrigir_texto(codigo))

            key = (ordem, marca, modelo, codigo)
            if key not in seen:
                seen.add(key)
                rows.append([ordem, marca, modelo, descricao, codigo])

            i = j

    rows.sort(key=lambda x: x[0])
    return rows


def parse_pdf(pdf_path: Path):
    rows = parse_with_pdfplumber_tables(pdf_path)
    if rows:
        return rows
    return parse_with_pymupdf_fallback(pdf_path)


if uploaded_file:
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / uploaded_file.name
        pdf_path.write_bytes(uploaded_file.read())

        rows = parse_pdf(pdf_path)

        if not rows:
            st.error("Nenhum item válido foi encontrado no PDF.")
            st.stop()

        df = pd.DataFrame(rows, columns=["ORDEM", "MARCA", "MODELO", "DESC", "CODIGO"])

        for i, row in df.iterrows():
            if not row["CODIGO"]:
                st.error(f"Código vazio na linha {i+1}")
                st.stop()

        def gerar(df, suf):
            linhas = [
                '<?xml version="1.0" encoding="ISO-8859-1"?>',
                '<ArrayOfItemSolicitacao>'
            ]

            for _, r in df.iterrows():
                linhas.extend([
                    "<ItemSolicitacao>",
                    f"<Marca>{escape_xml(limpar_iso(r['MARCA']))}</Marca>",
                    f"<Modelo>{escape_xml(limpar_iso(clean(r['MODELO']) + suf))}</Modelo>",
                    f"<Nome>{escape_xml(limpar_iso(limitar(r['DESC'])))}</Nome>",
                    "<CodigosBarras>",
                    f"<Codigo>{escape_xml(limpar_iso(r['CODIGO']))}</Codigo>",
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
        with open(zip_path, "rb") as f:
            st.download_button("Baixar ZIP", f, "resultado_final.zip")
