import streamlit as st
import pdfplumber
import fitz
import re
import pandas as pd
from pathlib import Path
import zipfile
import tempfile
from ftfy import fix_text
import sqlite3
from datetime import datetime

# =========================
# CONFIG
# =========================

st.set_page_config(page_title="C XML BR Engine", layout="wide")

# =========================
# DATABASE
# =========================

conn = sqlite3.connect("certificados.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS certificados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_bri TEXT UNIQUE,
    produto TEXT,
    data_emissao TEXT,
    data_validade TEXT,
    arquivo_pdf TEXT,
    data_cadastro TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    certificado_id INTEGER,
    ordem INTEGER,
    marca TEXT,
    modelo TEXT,
    nome TEXT,
    codigo TEXT,
    FOREIGN KEY(certificado_id) REFERENCES certificados(id)
)
""")

conn.commit()

# =========================
# HELPERS
# =========================

def clean(x):
    if x is None:
        return ""
    return re.sub(r"\s+", " ", str(x).replace("\n", " ")).strip()


def corrigir_texto(texto):
    if texto is None:
        return ""
    return fix_text(str(texto))


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


def extrair_dados_certificado(pdf_path):

    doc = fitz.open(str(pdf_path))
    texto = ""

    for page in doc:
        texto += page.get_text()

    texto = corrigir_texto(texto)

    ip_bri = None
    produto = None
    data_emissao = None
    data_validade = None

    ip_match = re.search(r"IP-BRI-\d+\/\d+-\d+", texto)

    if ip_match:
        ip_bri = ip_match.group(0)

    produto_match = re.search(r"Produto:\s*(.+)", texto)

    if produto_match:
        produto = clean(produto_match.group(1))

    datas = re.findall(r"\d{2}/\d{2}/\d{4}", texto)

    if len(datas) >= 2:
        data_emissao = datas[0]
        data_validade = datas[1]

    return {
        "ip_bri": ip_bri,
        "produto": produto,
        "data_emissao": data_emissao,
        "data_validade": data_validade
    }


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

                    rows.append([
                        ordem,
                        marca,
                        modelo,
                        nome,
                        codigo
                    ])

    rows.sort(key=lambda x: x[0])

    return rows


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

# =========================
# TABS
# =========================

aba1, aba2 = st.tabs([
    "PDF → XML",
    "Banco de Certificados"
])

# =========================
# ABA 1
# =========================

with aba1:

    st.title("C XML BR Engine - PDF → XML")

    uploaded_file = st.file_uploader(
        "Envie o PDF",
        type="pdf"
    )

    if uploaded_file:

        with tempfile.TemporaryDirectory() as tmpdir:

            pdf_path = Path(tmpdir) / uploaded_file.name

            pdf_path.write_bytes(uploaded_file.read())

            rows = parse_pdf(pdf_path)

            if not rows:
                st.error("Nenhum item válido encontrado")
                st.stop()

            df = pd.DataFrame(
                rows,
                columns=[
                    "ORDEM",
                    "MARCA",
                    "MODELO",
                    "NOME",
                    "CODIGO"
                ]
            )

            st.success("Itens extraídos com sucesso ✅")

            st.dataframe(df)

            xml_comma = gerar_xml(df, ",")
            xml_dot = gerar_xml(df, ".")

            zip_path = Path(tmpdir) / "resultado_xml.zip"

            with zipfile.ZipFile(zip_path, "w") as zipf:

                zipf.writestr(
                    "xml_virgula.xml",
                    xml_comma.encode(
                        "ISO-8859-1",
                        errors="replace"
                    )
                )

                zipf.writestr(
                    "xml_ponto.xml",
                    xml_dot.encode(
                        "ISO-8859-1",
                        errors="replace"
                    )
                )

            with open(zip_path, "rb") as f:

                st.download_button(
                    "Baixar XMLs",
                    f,
                    "resultado_xml.zip"
                )

# =========================
# ABA 2
# =========================

with aba2:

    st.title("Banco de Certificados")

    banco_file = st.file_uploader(
        "Envie um certificado PDF",
        type="pdf",
        key="banco_pdf"
    )

    if banco_file:

        with tempfile.TemporaryDirectory() as tmpdir:

            pdf_path = Path(tmpdir) / banco_file.name

            pdf_path.write_bytes(banco_file.read())

            dados_certificado = extrair_dados_certificado(pdf_path)

            rows = parse_pdf(pdf_path)

            st.subheader("Dados do Certificado")

            st.write(dados_certificado)

            if st.button("Salvar no banco"):

                try:

                    cursor.execute("""
                    INSERT INTO certificados (
                        ip_bri,
                        produto,
                        data_emissao,
                        data_validade,
                        arquivo_pdf,
                        data_cadastro
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        dados_certificado["ip_bri"],
                        dados_certificado["produto"],
                        dados_certificado["data_emissao"],
                        dados_certificado["data_validade"],
                        banco_file.name,
                        datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                    ))

                    conn.commit()

                    certificado_id = cursor.lastrowid

                    for r in rows:

                        cursor.execute("""
                        INSERT INTO itens (
                            certificado_id,
                            ordem,
                            marca,
                            modelo,
                            nome,
                            codigo
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            certificado_id,
                            r[0],
                            r[1],
                            r[2],
                            r[3],
                            r[4]
                        ))

                    conn.commit()

                    st.success("Certificado salvo com sucesso ✅")

                except sqlite3.IntegrityError:

                    st.error("Esse IP-BRI já existe no banco.")

    st.divider()

    st.subheader("Consultar Certificados")

    busca = st.text_input("Buscar IP-BRI")

    query = """
    SELECT
        id,
        ip_bri,
        produto,
        data_emissao,
        data_validade
    FROM certificados
    """

    params = ()

    if busca:

        query += " WHERE ip_bri LIKE ?"
        params = (f"%{busca}%",)

    certificados = pd.read_sql_query(
        query,
        conn,
        params=params
    )

    st.dataframe(certificados)

    if not certificados.empty:

        cert_id = st.selectbox(
            "Selecionar certificado",
            certificados["id"]
        )

        itens = pd.read_sql_query("""
        SELECT
            ordem,
            marca,
            modelo,
            nome,
            codigo
        FROM itens
        WHERE certificado_id = ?
        ORDER BY ordem
        """, conn, params=(cert_id,))

        st.subheader("Itens do Certificado")

        st.dataframe(itens)
