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

st.set_page_config(page_title="C XML BR Engine", layout="wide")

DB_PATH = "certificados.db"

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS certificados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_bri TEXT UNIQUE,
    produto TEXT,
    ce_bri TEXT,
    data_emissao TEXT,
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

try:
    cursor.execute("ALTER TABLE certificados ADD COLUMN ce_bri TEXT")
    conn.commit()
except:
    pass


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


def verificar_codigos_duplicados(df):
    duplicados = df[df.duplicated(subset=["CODIGO"], keep=False)].copy()

    if not duplicados.empty:
        duplicados = duplicados.sort_values(by="CODIGO")

    return duplicados


def extrair_dados_certificado(pdf_path):
    doc = fitz.open(str(pdf_path))

    texto = ""
    for page in doc:
        texto += page.get_text() + "\n"

    texto = corrigir_texto(texto)

    ip_bri = None
    produto = None
    ce_bri = None
    data_emissao = None

    ip_match = re.search(r"IP-BRI-\d+\/\d+-\d+", texto)
    if ip_match:
        ip_bri = ip_match.group(0)

    ce_bri_match = re.search(
        r"CE-BRI-[A-Z0-9\-]+",
        texto,
        flags=re.IGNORECASE
    )
    if ce_bri_match:
        ce_bri = ce_bri_match.group(0).upper()

    produto_match = re.search(r"Produto:\s*(.+)", texto)
    if produto_match:
        produto = clean(produto_match.group(1))

    emissao_match = re.search(
        r"Data de Emissão:\s*(\d{2}/\d{2}/\d{4})",
        texto,
        flags=re.IGNORECASE
    )
    if emissao_match:
        data_emissao = emissao_match.group(1)

    return {
        "ip_bri": ip_bri,
        "produto": produto,
        "ce_bri": ce_bri,
        "data_emissao": data_emissao
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

                    rows.append([ordem, marca, modelo, nome, codigo])

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


def exportar_todos_itens():
    return pd.read_sql_query("""
    SELECT
        i.marca AS marca,
        i.modelo AS modelo,
        i.nome AS nome,
        i.codigo AS codigo,
        c.ip_bri AS ip_bri,
        c.ce_bri AS ce_bri,
        c.produto AS produto,
        c.data_emissao AS data_emissao,
        i.ordem AS ordem,
        c.arquivo_pdf AS arquivo_pdf,
        c.data_cadastro AS data_cadastro
    FROM itens i
    INNER JOIN certificados c
    ON c.id = i.certificado_id
    ORDER BY i.marca, i.modelo, c.ip_bri, i.ordem
    """, conn)


aba1, aba2 = st.tabs([
    "PDF → XML",
    "Banco de Certificados"
])


with aba1:
    st.title("C XML BR Engine - PDF → XML")

    uploaded_file = st.file_uploader(
        "Envie o PDF",
        type="pdf",
        key="xml_pdf"
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
                columns=["ORDEM", "MARCA", "MODELO", "NOME", "CODIGO"]
            )

            st.success("Itens extraídos com sucesso ✅")
            st.dataframe(df, use_container_width=True)

            xml_comma = gerar_xml(df, ",")
            xml_dot = gerar_xml(df, ".")

            zip_path = Path(tmpdir) / "resultado_xml.zip"

            with zipfile.ZipFile(zip_path, "w") as zipf:
                zipf.writestr(
                    "xml_virgula.xml",
                    xml_comma.encode("ISO-8859-1", errors="replace")
                )
                zipf.writestr(
                    "xml_ponto.xml",
                    xml_dot.encode("ISO-8859-1", errors="replace")
                )

            with open(zip_path, "rb") as f:
                st.download_button(
                    "Baixar XMLs",
                    f,
                    "resultado_xml.zip"
                )


with aba2:
    st.title("Banco de Certificados")

    st.subheader("Backup do Banco")

    backup_upload = st.file_uploader(
        "Importar backup certificados.db",
        type=["db"],
        key="backup_db"
    )

    if backup_upload:
        conn.close()

        with open(DB_PATH, "wb") as f:
            f.write(backup_upload.read())

        st.success("Backup importado com sucesso. Recarregue o app.")
        st.stop()

    if Path(DB_PATH).exists():
        with open(DB_PATH, "rb") as f:
            st.download_button(
                "Baixar backup atualizado",
                f,
                "certificados.db",
                "application/octet-stream"
            )

    st.divider()

    st.subheader("Exportar banco completo")

    todos_itens = exportar_todos_itens()

    if todos_itens.empty:
        st.info("Ainda não há itens cadastrados para exportar.")
    else:
        st.dataframe(todos_itens, use_container_width=True)

        st.download_button(
            "Baixar arquivo completo com todas as marcas",
            todos_itens.to_csv(index=False, sep=";").encode(
                "ISO-8859-1",
                errors="replace"
            ),
            "banco_completo_todas_as_marcas.csv",
            "text/csv"
        )

    st.divider()

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

            col1, col2, col3, col4 = st.columns(4)

            col1.metric("IP-BRI", dados_certificado["ip_bri"] or "Não encontrado")
            col2.metric("CE-BRI", dados_certificado["ce_bri"] or "Não encontrado")
            col3.metric("Produto", dados_certificado["produto"] or "Não encontrado")
            col4.metric("Data Emissão", dados_certificado["data_emissao"] or "Não encontrado")

            if rows:
                df_preview = pd.DataFrame(
                    rows,
                    columns=["ORDEM", "MARCA", "MODELO", "NOME", "CODIGO"]
                )

                st.subheader("Itens encontrados")
                st.dataframe(df_preview, use_container_width=True)

                duplicados = verificar_codigos_duplicados(df_preview)

                if not duplicados.empty:
                    st.warning("Foram encontrados códigos duplicados.")
                    st.dataframe(duplicados, use_container_width=True)

                if st.button("Salvar no banco"):
                    if not dados_certificado["ip_bri"]:
                        st.error("IP-BRI não encontrado.")
                    else:
                        try:
                            cursor.execute("""
                            INSERT INTO certificados (
                                ip_bri,
                                produto,
                                ce_bri,
                                data_emissao,
                                arquivo_pdf,
                                data_cadastro
                            )
                            VALUES (?, ?, ?, ?, ?, ?)
                            """, (
                                dados_certificado["ip_bri"],
                                dados_certificado["produto"],
                                dados_certificado["ce_bri"],
                                dados_certificado["data_emissao"],
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

    st.subheader("Pesquisar item no banco")

    tipo_busca = st.selectbox(
        "Pesquisar por",
        ["Referência / Modelo", "Código de Barras"]
    )

    termo_busca = st.text_input(
        "Digite a referência/modelo ou código de barras"
    )

    if termo_busca:
        if tipo_busca == "Referência / Modelo":
            resultado_item = pd.read_sql_query("""
            SELECT
                i.marca AS marca,
                i.modelo AS modelo,
                i.nome AS nome,
                i.codigo AS codigo,
                c.ip_bri AS ip_bri,
                c.ce_bri AS ce_bri,
                c.produto AS produto,
                c.data_emissao AS data_emissao,
                i.ordem AS ordem
            FROM itens i
            INNER JOIN certificados c
            ON c.id = i.certificado_id
            WHERE i.modelo LIKE ?
            ORDER BY i.marca, i.modelo, c.ip_bri, i.ordem
            """, conn, params=(f"%{termo_busca}%",))
        else:
            resultado_item = pd.read_sql_query("""
            SELECT
                i.marca AS marca,
                i.modelo AS modelo,
                i.nome AS nome,
                i.codigo AS codigo,
                c.ip_bri AS ip_bri,
                c.ce_bri AS ce_bri,
                c.produto AS produto,
                c.data_emissao AS data_emissao,
                i.ordem AS ordem
            FROM itens i
            INNER JOIN certificados c
            ON c.id = i.certificado_id
            WHERE i.codigo LIKE ?
            ORDER BY i.marca, i.modelo, c.ip_bri, i.ordem
            """, conn, params=(f"%{termo_busca}%",))

        if resultado_item.empty:
            st.warning("Nenhum item encontrado.")
        else:
            st.success("Item encontrado no banco ✅")
            st.dataframe(resultado_item, use_container_width=True)

            st.download_button(
                "Baixar resultado da pesquisa em CSV",
                resultado_item.to_csv(index=False, sep=";").encode(
                    "ISO-8859-1",
                    errors="replace"
                ),
                "resultado_pesquisa_item.csv",
                "text/csv"
            )

    st.divider()

    st.subheader("Filtro geral por Marca")

    marcas_banco = pd.read_sql_query("""
    SELECT DISTINCT marca
    FROM itens
    WHERE marca IS NOT NULL
    AND marca != ''
    ORDER BY marca
    """, conn)

    if not marcas_banco.empty:
        marca_filtro = st.selectbox(
            "Selecione uma marca",
            marcas_banco["marca"].tolist()
        )

        resultado_marca = pd.read_sql_query("""
        SELECT
            i.marca AS marca,
            i.modelo AS modelo,
            i.nome AS nome,
            i.codigo AS codigo,
            c.ip_bri AS ip_bri,
            c.ce_bri AS ce_bri,
            c.produto AS produto,
            c.data_emissao AS data_emissao,
            i.ordem AS ordem
        FROM itens i
        INNER JOIN certificados c
        ON c.id = i.certificado_id
        WHERE i.marca = ?
        ORDER BY i.marca, i.modelo, c.ip_bri, i.ordem
        """, conn, params=(marca_filtro,))

        st.dataframe(resultado_marca, use_container_width=True)

        if not resultado_marca.empty:
            st.download_button(
                "Baixar CSV da marca",
                resultado_marca.to_csv(index=False, sep=";").encode(
                    "ISO-8859-1",
                    errors="replace"
                ),
                f"marca_{marca_filtro}.csv",
                "text/csv"
            )
