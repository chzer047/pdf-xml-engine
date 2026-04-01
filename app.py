import streamlit as st
import fitz  # PyMuPDF
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


def parse_pdf_with_pymupdf(pdf_path: Path):
    rows = []
    seen = set()

    doc = fitz.open(pdf_path)

    for page in doc:
        text = page.get_text("text")
        lines = [clean(line) for line in text.splitlines() if clean(line)]

        i = 0
        while i < len(lines):
            line = lines[i]

            # início de item: 001 MARCA ...
            m = re.match(r"^(\d{3})\s+(.+)$", line)
            if not m:
                i += 1
                continue

            ordem = int(m.group(1))
            rest = m.group(2)

            # ignora cabeçalhos e textos fora da listagem
            if rest.startswith("PAI ") or "Rol de Produtos" in rest or "Nome da Família" in rest:
                i += 1
                continue

            # monta bloco do item até achar código de barras
            block = [rest]
            j = i + 1
            codigo = None

            while j < len(lines):
                current = lines[j]

                # se encontrou próxima ordem antes de achar código, aborta item atual
                if re.match(r"^\d{3}\s+.+$", current):
                    break

                block.append(current)

                # código de barras costuma estar sozinho na linha
                code_match = re.fullmatch(r"[\d\*\s]+", current)
                if code_match:
                    codigo = clean(current).replace(" ", "").replace("*", "")
                    j += 1
                    break

                j += 1

            if not codigo:
                i += 1
                continue

            full = " ".join(block[:-1]).strip() if len(block) > 1 else block[0]

            # tenta separar marca / modelo / descrição
            # exemplos:
            # SK TOYS SK-1169 - BRINQUEDO CARRINHO ...
            # CFTOYS CF1028001 - BRINQUEDO TANQUE DE GUERRA ...
            sep = " - "
            if sep not in full:
                i = j
                continue

            left, right = full.split(sep, 1)

            left_parts = left.split()
            if len(left_parts) < 2:
                i = j
                continue

            # modelo = último token da esquerda
            modelo_codigo = left_parts[-1]
            marca = " ".join(left_parts[:-1])

            modelo = f"{modelo_codigo} - {right.split(' BRINQUEDO', 1)[0].strip()}" if " BRINQUEDO" in " " + right else f"{modelo_codigo} - {right.strip()}"

            descricao = right.strip()

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


if uploaded_file:
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "input.pdf"
        pdf_path.write_bytes(uploaded_file.read())

        rows = parse_pdf_with_pymupdf(pdf_path)

        if not rows:
            st.error("Nenhum item válido foi encontrado no PDF.")
            st.stop()

        df = pd.DataFrame(rows, columns=["ORDEM", "MARCA", "MODELO", "DESC", "CODIGO"])

        # validação
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

        xml1 = gerar(df, ",")
        xml2 = gerar(df, ".")

        zip_path = Path(tmpdir) / "resultado.zip"

        with zipfile.ZipFile(zip_path, "w") as zipf:
            zipf.writestr("xml_comma.xml", xml1)
            zipf.writestr("xml_dot.xml", xml2)

        st.success("Processado com sucesso!")
        with open(zip_path, "rb") as f:
            st.download_button("Baixar ZIP", f, "resultado.zip")
