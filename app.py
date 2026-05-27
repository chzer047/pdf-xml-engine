# ==========================================
# C XML BR Engine
# COMPLETO + REV + HISTÓRICO + BANCO
# ==========================================

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

# ==========================================
# CONFIG
# ==========================================

st.set_page_config(
    page_title="C XML BR Engine",
    layout="wide"
)

DB_PATH = "certificados.db"

# ==========================================
# CONEXÃO
# ==========================================

conn = sqlite3.connect(
    DB_PATH,
    check_same_thread=False
)

cursor = conn.cursor()

# ==========================================
# TABELAS
# ==========================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS certificados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_bri TEXT UNIQUE,
    produto TEXT,
    ce_bri TEXT,
    rev INTEGER,
    data_emissao TEXT,
    arquivo_pdf TEXT,
    data_cadastro TEXT,
    data_atualizacao TEXT
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
    codigo TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS historico_alteracoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_bri TEXT,
    rev_antiga INTEGER,
    rev_nova INTEGER,
    modelo TEXT,
    codigo TEXT,
    tipo_alteracao TEXT,
    campo_alterado TEXT,
    valor_antigo TEXT,
    valor_novo TEXT,
    arquivo_pdf TEXT,
    data_hora TEXT
)
""")

conn.commit()

# ==========================================
# FUNÇÕES
# ==========================================

def clean(x):

    if x is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(x).replace("\n", " ")
    ).strip()


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

        nome = nome.replace(
            "PRODUZIDO",
            "PROD."
        )

        nome = nome.replace(
            "INDICATIVO",
            "IND."
        )

        nome = nome.replace(
            "RESTRITIVO",
            "REST."
        )

        nome = nome[:200]

    return nome


def escape_xml(texto):

    return str(texto)\
        .replace("&", "&amp;")\
        .replace("<", "&lt;")\
        .replace(">", "&gt;")


def verificar_codigos_duplicados(df):

    duplicados = df[
        df.duplicated(
            subset=["CODIGO"],
            keep=False
        )
    ].copy()

    if not duplicados.empty:
        duplicados = duplicados.sort_values(
            by="CODIGO"
        )

    return duplicados


# ==========================================
# REV
# ==========================================

def extrair_rev(texto):

    texto = corrigir_texto(texto)

    padroes = [
        r"\bREV\.?\s*:?\s*(\d+)",
        r"\bREVISÃO\s*:?\s*(\d+)",
        r"\bREVISAO\s*:?\s*(\d+)"
    ]

    for padrao in padroes:

        match = re.search(
            padrao,
            texto,
            flags=re.IGNORECASE
        )

        if match:
            return int(match.group(1))

    return 0


# ==========================================
# EXTRAÇÃO CERTIFICADO
# ==========================================

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

    ip_match = re.search(
        r"IP-BRI-\d+\/\d+-\d+",
        texto
    )

    if ip_match:
        ip_bri = ip_match.group(0)

    ce_match = re.search(
        r"CE-BRI-[A-Z0-9\-]+",
        texto,
        flags=re.IGNORECASE
    )

    if ce_match:
        ce_bri = ce_match.group(0).upper()

    produto_match = re.search(
        r"Produto:\s*(.+)",
        texto
    )

    if produto_match:
        produto = clean(produto_match.group(1))

    emissao_match = re.search(
        r"Data de Emissão:\s*(\d{2}/\d{2}/\d{4})",
        texto,
        flags=re.IGNORECASE
    )

    if emissao_match:
        data_emissao = emissao_match.group(1)

    rev = extrair_rev(texto)

    return {
        "ip_bri": ip_bri,
        "produto": produto,
        "ce_bri": ce_bri,
        "rev": rev,
        "data_emissao": data_emissao
    }


# ==========================================
# PARSE PDF
# ==========================================

def parse_pdf(pdf_path):

    rows = []

    with pdfplumber.open(str(pdf_path)) as pdf:

        for page in pdf.pages:

            for table in page.extract_tables() or []:

                for row in table:

                    if not row or len(row) < 6:
                        continue

                    ordem = clean(row[1])

                    if not re.fullmatch(
                        r"\d{3}",
                        ordem
                    ):
                        continue

                    ordem = int(ordem)

                    marca = clean(
                        corrigir_texto(row[2])
                    )

                    modelo = clean(
                        corrigir_texto(row[3])
                    )

                    nome = clean(
                        corrigir_texto(row[4])
                    )

                    codigo_raw = clean(
                        corrigir_texto(row[5])
                    )

                    codigo = extrair_codigo_unico(
                        codigo_raw
                    )

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


# ==========================================
# XML
# ==========================================

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


# ==========================================
# HISTÓRICO
# ==========================================

def registrar_historico(
    ip_bri,
    rev_antiga,
    rev_nova,
    modelo,
    codigo,
    tipo,
    campo,
    antigo,
    novo,
    arquivo
):

    cursor.execute("""
    INSERT INTO historico_alteracoes (
        ip_bri,
        rev_antiga,
        rev_nova,
        modelo,
        codigo,
        tipo_alteracao,
        campo_alterado,
        valor_antigo,
        valor_novo,
        arquivo_pdf,
        data_hora
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ip_bri,
        rev_antiga,
        rev_nova,
        modelo,
        codigo,
        tipo,
        campo,
        antigo,
        novo,
        arquivo,
        datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    ))

    conn.commit()


def comparar_itens(
    ip_bri,
    rev_antiga,
    rev_nova,
    antigos,
    novos,
    arquivo
):

    antigos_dict = {
        r[2]: r for r in antigos
    }

    novos_dict = {
        r[2]: r for r in novos
    }

    for modelo in antigos_dict:

        if modelo not in novos_dict:

            antigo = antigos_dict[modelo]

            registrar_historico(
                ip_bri,
                rev_antiga,
                rev_nova,
                antigo[2],
                antigo[4],
                "ITEM_REMOVIDO",
                "",
                f"{antigo}",
                "",
                arquivo
            )

    for modelo in novos_dict:

        if modelo not in antigos_dict:

            novo = novos_dict[modelo]

            registrar_historico(
                ip_bri,
                rev_antiga,
                rev_nova,
                novo[2],
                novo[4],
                "ITEM_NOVO",
                "",
                "",
                f"{novo}",
                arquivo
            )

    for modelo in novos_dict:

        if modelo in antigos_dict:

            antigo = antigos_dict[modelo]
            novo = novos_dict[modelo]

            campos = {
                "MARCA": (antigo[1], novo[1]),
                "NOME": (antigo[3], novo[3]),
                "CODIGO": (antigo[4], novo[4])
            }

            for campo in campos:

                antigo_valor, novo_valor = campos[campo]

                if str(antigo_valor) != str(novo_valor):

                    registrar_historico(
                        ip_bri,
                        rev_antiga,
                        rev_nova,
                        modelo,
                        novo[4],
                        "CAMPO_ALTERADO",
                        campo,
                        antigo_valor,
                        novo_valor,
                        arquivo
                    )


# ==========================================
# SALVAR / ATUALIZAR
# ==========================================

def salvar_ou_atualizar_certificado(
    dados_certificado,
    rows,
    nome_arquivo
):

    ip_bri = dados_certificado["ip_bri"]
    rev_nova = dados_certificado["rev"]

    if not ip_bri:
        return "erro", "IP-BRI não encontrado"

    existente = cursor.execute("""
    SELECT id, rev
    FROM certificados
    WHERE ip_bri = ?
    """, (ip_bri,)).fetchone()

    if not existente:

        cursor.execute("""
        INSERT INTO certificados (
            ip_bri,
            produto,
            ce_bri,
            rev,
            data_emissao,
            arquivo_pdf,
            data_cadastro,
            data_atualizacao
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ip_bri,
            dados_certificado["produto"],
            dados_certificado["ce_bri"],
            rev_nova,
            dados_certificado["data_emissao"],
            nome_arquivo,
            datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
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

        return "novo", "Novo certificado salvo"

    certificado_id = existente[0]
    rev_antiga = int(existente[1] or 0)

    if rev_nova <= rev_antiga:
        return "ignorado", "REV menor ou igual"

    antigos = cursor.execute("""
    SELECT
        ordem,
        marca,
        modelo,
        nome,
        codigo
    FROM itens
    WHERE certificado_id = ?
    """, (certificado_id,)).fetchall()

    comparar_itens(
        ip_bri,
        rev_antiga,
        rev_nova,
        antigos,
        rows,
        nome_arquivo
    )

    cursor.execute("""
    DELETE FROM itens
    WHERE certificado_id = ?
    """, (certificado_id,))

    cursor.execute("""
    UPDATE certificados
    SET
        produto = ?,
        ce_bri = ?,
        rev = ?,
        data_emissao = ?,
        arquivo_pdf = ?,
        data_atualizacao = ?
    WHERE id = ?
    """, (
        dados_certificado["produto"],
        dados_certificado["ce_bri"],
        rev_nova,
        dados_certificado["data_emissao"],
        nome_arquivo,
        datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        certificado_id
    ))

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

    return "atualizado", f"Atualizado REV {rev_antiga} → {rev_nova}"

# ==========================================
# EXPORTAR
# ==========================================

def exportar_todos_itens():

    return pd.read_sql_query("""
    SELECT
        i.marca,
        i.modelo,
        i.nome,
        i.codigo,
        c.ip_bri,
        c.ce_bri,
        c.rev,
        c.produto,
        c.data_emissao,
        i.ordem
    FROM itens i
    INNER JOIN certificados c
    ON c.id = i.certificado_id
    ORDER BY i.marca, i.modelo
    """, conn)

# ==========================================
# TABS
# ==========================================

aba1, aba2, aba3, aba4 = st.tabs([
    "PDF → XML",
    "Banco de Certificados",
    "Consultar IP-BRI",
    "Registros"
])

# ==========================================
# ABA 1
# ==========================================

with aba1:

    st.title("PDF → XML")

    uploaded_file = st.file_uploader(
        "Envie o PDF",
        type="pdf",
        key="xml_pdf"
    )

    if uploaded_file:

        with tempfile.TemporaryDirectory() as tmpdir:

            pdf_path = Path(tmpdir) / uploaded_file.name

            pdf_path.write_bytes(
                uploaded_file.read()
            )

            rows = parse_pdf(pdf_path)

            if not rows:
                st.error("Nenhum item encontrado")
                st.stop()

            dados_certificado = extrair_dados_certificado(
                pdf_path
            )

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

            st.success("Itens extraídos")

            st.dataframe(
                df,
                use_container_width=True
            )

            st.info(
                f"""
IP-BRI: {dados_certificado["ip_bri"]}

CE-BRI: {dados_certificado["ce_bri"]}

REV: {dados_certificado["rev"]}
"""
            )

            duplicados = verificar_codigos_duplicados(df)

            if not duplicados.empty:
                st.warning("Foram encontrados códigos duplicados.")
                st.dataframe(duplicados, use_container_width=True)

            status, mensagem = salvar_ou_atualizar_certificado(
                dados_certificado,
                rows,
                uploaded_file.name
            )

            if status == "novo":
                st.success(mensagem)

            elif status == "atualizado":
                st.warning(mensagem)

            elif status == "ignorado":
                st.info(mensagem)

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

# ==========================================
# ABA 2
# ==========================================

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

        st.success("Backup importado com sucesso.")
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

    todos = exportar_todos_itens()

    if not todos.empty:

        st.download_button(
            "Baixar banco completo",
            todos.to_csv(
                index=False,
                sep=";"
            ).encode(
                "ISO-8859-1",
                errors="replace"
            ),
            "banco_completo.csv",
            "text/csv"
        )

    st.divider()

    st.subheader("Pesquisar item no banco")

    tipo_busca = st.selectbox(
        "Pesquisar por",
        ["Referência / Modelo", "Código de Barras"],
        key="tipo_busca"
    )

    termo_busca = st.text_input(
        "Digite a referência/modelo ou código",
        key="busca_item"
    )

    if termo_busca:

        campo = "i.modelo" if tipo_busca == "Referência / Modelo" else "i.codigo"

        resultado_item = pd.read_sql_query(f"""
        SELECT
            i.marca,
            i.modelo,
            i.nome,
            i.codigo,
            c.ip_bri,
            c.ce_bri,
            c.rev,
            c.produto,
            c.data_emissao,
            i.ordem
        FROM itens i
        INNER JOIN certificados c
        ON c.id = i.certificado_id
        WHERE {campo} LIKE ?
        ORDER BY i.marca, i.modelo
        """, conn, params=(f"%{termo_busca}%",))

        if resultado_item.empty:
            st.warning("Nenhum item encontrado.")
        else:
            st.success("Item encontrado ✅")
            st.dataframe(resultado_item, use_container_width=True)

    st.divider()

    st.subheader("Itens Repetidos")

    if st.button("Ver itens repetidos"):

        itens_repetidos = pd.read_sql_query("""
        SELECT
            i.marca,
            i.modelo,
            i.nome,
            i.codigo,
            c.ip_bri,
            c.ce_bri
        FROM itens i
        INNER JOIN certificados c
        ON c.id = i.certificado_id
        WHERE i.codigo IN (
            SELECT codigo
            FROM itens
            GROUP BY codigo
            HAVING COUNT(*) > 1
        )
        ORDER BY i.codigo
        """, conn)

        if itens_repetidos.empty:
            st.success("Nenhum item repetido encontrado ✅")
        else:
            st.warning("Itens repetidos encontrados.")
            st.dataframe(itens_repetidos, use_container_width=True)

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
            marcas_banco["marca"].tolist(),
            key="marca_filtro"
        )

        resultado_marca = pd.read_sql_query("""
        SELECT
            i.marca,
            i.modelo,
            i.nome,
            i.codigo,
            c.ip_bri,
            c.ce_bri,
            c.rev,
            c.produto,
            c.data_emissao,
            i.ordem
        FROM itens i
        INNER JOIN certificados c
        ON c.id = i.certificado_id
        WHERE i.marca = ?
        ORDER BY i.modelo
        """, conn, params=(marca_filtro,))

        st.dataframe(resultado_marca, use_container_width=True)

        st.download_button(
            "Baixar CSV da marca",
            resultado_marca.to_csv(
                index=False,
                sep=";"
            ).encode(
                "ISO-8859-1",
                errors="replace"
            ),
            f"{marca_filtro}.csv",
            "text/csv"
        )

    st.divider()

    st.subheader("Histórico por IP-BRI")

    ip_historico = st.text_input(
        "Digite o IP-BRI",
        key="historico_ip"
    )

    if ip_historico:

        historico = pd.read_sql_query("""
        SELECT
            ip_bri,
            rev_antiga,
            rev_nova,
            modelo,
            codigo,
            tipo_alteracao,
            campo_alterado,
            valor_antigo,
            valor_novo,
            arquivo_pdf,
            data_hora
        FROM historico_alteracoes
        WHERE ip_bri LIKE ?
        ORDER BY id DESC
        """, conn, params=(f"%{ip_historico}%",))

        if historico.empty:

            st.warning("Nenhum histórico encontrado.")

        else:

            grupos = historico.groupby(
                [
                    "rev_antiga",
                    "rev_nova",
                    "arquivo_pdf",
                    "data_hora"
                ],
                dropna=False
            )

            for (
                rev_antiga,
                rev_nova,
                arquivo_pdf,
                data_hora
            ), grupo in grupos:

                with st.expander(
                    f"REV {rev_antiga} → REV {rev_nova} | {data_hora}"
                ):

                    col1, col2, col3 = st.columns(3)

                    col1.metric(
                        "Itens novos",
                        len(grupo[
                            grupo["tipo_alteracao"] == "ITEM_NOVO"
                        ])
                    )

                    col2.metric(
                        "Itens removidos",
                        len(grupo[
                            grupo["tipo_alteracao"] == "ITEM_REMOVIDO"
                        ])
                    )

                    col3.metric(
                        "Campos alterados",
                        len(grupo[
                            grupo["tipo_alteracao"] == "CAMPO_ALTERADO"
                        ])
                    )

                    for _, row in grupo.iterrows():

                        tipo = row["tipo_alteracao"]

                        if tipo == "ITEM_REMOVIDO":

                            st.error(
                                f"""
🗑️ ITEM REMOVIDO

Modelo: {row["modelo"]}

Código: {row["codigo"]}
"""
                            )

                        elif tipo == "ITEM_NOVO":

                            st.success(
                                f"""
➕ ITEM NOVO

Modelo: {row["modelo"]}

Código: {row["codigo"]}
"""
                            )

                        elif tipo == "CAMPO_ALTERADO":

                            st.warning(
                                f"""
✏️ CAMPO ALTERADO

Modelo: {row["modelo"]}

Código: {row["codigo"]}

Campo: {row["campo_alterado"]}

ANTES:
{row["valor_antigo"]}

DEPOIS:
{row["valor_novo"]}
"""
                            )

# ==========================================
# ABA 3
# ==========================================

with aba3:

    st.title("Consultar IP-BRI")

    busca_ip = st.text_input(
        "Digite o IP-BRI que deseja consultar",
        key="consulta_ip_bri_aba3"
    )

    if busca_ip:

        itens_ip = pd.read_sql_query("""
        SELECT
            i.marca,
            i.modelo,
            i.nome,
            i.codigo,
            c.ip_bri,
            c.ce_bri,
            c.rev,
            c.produto,
            c.data_emissao,
            i.ordem
        FROM itens i
        INNER JOIN certificados c
        ON c.id = i.certificado_id
        WHERE c.ip_bri LIKE ?
        ORDER BY i.marca, i.modelo, i.ordem
        """, conn, params=(f"%{busca_ip}%",))

        if itens_ip.empty:

            st.warning(
                "Nenhum item encontrado para esse IP-BRI."
            )

        else:

            st.success(
                f"{len(itens_ip)} itens encontrados ✅"
            )

            st.dataframe(
                itens_ip,
                use_container_width=True
            )

            st.download_button(
                "Baixar itens deste IP-BRI em CSV",
                itens_ip.to_csv(
                    index=False,
                    sep=";"
                ).encode(
                    "ISO-8859-1",
                    errors="replace"
                ),
                f"{busca_ip.replace('/', '-')}.csv",
                "text/csv"
            )
# ==========================================
# ABA 4 - REGISTROS
# ==========================================

with aba4:

    st.title("Registros")

    st.info("""
Envie o Excel de registros da BOLSA.

Cada aba do Excel = uma fábrica.

O sistema irá:
- identificar a fábrica pela aba;
- ler coluna FAMÍLIA;
- ler coluna REGISTRO;
- cruzar automaticamente com CE-BRI/IP-BRI futuramente.
""")

    registro_excel = st.file_uploader(
        "Envie o Excel de Registros",
        type=["xlsx", "xls"],
        key="excel_registros"
    )

    if registro_excel:

        try:

            excel = pd.ExcelFile(registro_excel)

            abas = excel.sheet_names

            st.success(f"{len(abas)} fábricas encontradas ✅")

            todas_fabricas = []

            for aba in abas:

                st.divider()

                st.subheader(f"Fábrica: {aba}")

                try:

                    df = pd.read_excel(
                        registro_excel,
                        sheet_name=aba
                    )

                    df.columns = [
                        str(c).strip().upper()
                        for c in df.columns
                    ]

                    coluna_familia = None
                    coluna_registro = None

                    for c in df.columns:

                        if "FAM" in c:
                            coluna_familia = c

                        if "REG" in c:
                            coluna_registro = c

                    if not coluna_familia or not coluna_registro:

                        st.warning(
                            f"Aba {aba} não possui colunas FAMÍLIA/REGISTRO válidas."
                        )

                        continue

                    df_filtrado = df[
                        [coluna_familia, coluna_registro]
                    ].copy()

                    df_filtrado.columns = [
                        "FAMILIA",
                        "REGISTRO"
                    ]

                    df_filtrado = df_filtrado.dropna(
                        subset=["FAMILIA"]
                    )

                    df_filtrado["FABRICA"] = aba

                    st.dataframe(
                        df_filtrado,
                        use_container_width=True
                    )

                    todas_fabricas.append(df_filtrado)

                except Exception as e:

                    st.error(
                        f"Erro na aba {aba}: {e}"
                    )

            if todas_fabricas:

                banco_registros = pd.concat(
                    todas_fabricas,
                    ignore_index=True
                )

                st.divider()

                st.subheader("Banco Geral de Registros")

                st.dataframe(
                    banco_registros,
                    use_container_width=True
                )

                st.download_button(
                    "Baixar registros tratados CSV",
                    banco_registros.to_csv(
                        index=False,
                        sep=";"
                    ).encode(
                        "ISO-8859-1",
                        errors="replace"
                    ),
                    "registros_tratados.csv",
                    "text/csv"
                )

        except Exception as e:

            st.error(f"Erro ao ler Excel: {e}")
