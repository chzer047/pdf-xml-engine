# ==========================================
# C XML BR Engine
# REV + Histórico Inteligente
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
# CONEXÃO DB
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
# FUNÇÕES GERAIS
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
# EXTRAIR DADOS CERTIFICADO
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


# ==========================================
# COMPARAR ITENS
# ==========================================

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

    # removidos
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

    # novos
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

    # alterados
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

    # ==========================================
    # NOVO
    # ==========================================

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

        registrar_historico(
            ip_bri,
            None,
            rev_nova,
            "",
            "",
            "CERTIFICADO_NOVO",
            "",
            "",
            f"Novo certificado com {len(rows)} itens",
            nome_arquivo
        )

        return "novo", "Novo certificado salvo"

    # ==========================================
    # EXISTENTE
    # ==========================================

    certificado_id = existente[0]
    rev_antiga = int(existente[1] or 0)

    if rev_nova <= rev_antiga:

        registrar_historico(
            ip_bri,
            rev_antiga,
            rev_nova,
            "",
            "",
            "REV_IGNORADA",
            "",
            f"REV banco: {rev_antiga}",
            f"REV enviada: {rev_nova}",
            nome_arquivo
        )

        return "ignorado", "REV menor ou igual"

    # itens antigos
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

    # apaga antigos
    cursor.execute("""
    DELETE FROM itens
    WHERE certificado_id = ?
    """, (certificado_id,))

    # atualiza certificado
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

    # insere novos
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

    registrar_historico(
        ip_bri,
        rev_antiga,
        rev_nova,
        "",
        "",
        "CERTIFICADO_ATUALIZADO",
        "",
        f"REV {rev_antiga}",
        f"REV {rev_nova}",
        nome_arquivo
    )

    return "atualizado", f"Atualizado REV {rev_antiga} → {rev_nova}"


# ==========================================
# EXPORTAR TUDO
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

aba1, aba2 = st.tabs([
    "PDF → XML",
    "Banco de Certificados"
])

# ==========================================
# ABA XML
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
# ABA BANCO
# ==========================================

with aba2:

    st.title("Banco de Certificados")

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

    st.subheader("Histórico por IP-BRI")

    ip_historico = st.text_input(
        "Digite o IP-BRI"
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

            st.warning(
                "Nenhum histórico encontrado"
            )

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

                qtd_novos = len(
                    grupo[
                        grupo["tipo_alteracao"] == "ITEM_NOVO"
                    ]
                )

                qtd_removidos = len(
                    grupo[
                        grupo["tipo_alteracao"] == "ITEM_REMOVIDO"
                    ]
                )

                qtd_alterados = len(
                    grupo[
                        grupo["tipo_alteracao"] == "CAMPO_ALTERADO"
                    ]
                )

                with st.expander(
                    f"REV {rev_antiga} → REV {rev_nova} | {data_hora}",
                    expanded=False
                ):

                    col1, col2, col3 = st.columns(3)

                    col1.metric(
                        "Itens novos",
                        qtd_novos
                    )

                    col2.metric(
                        "Itens removidos",
                        qtd_removidos
                    )

                    col3.metric(
                        "Campos alterados",
                        qtd_alterados
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

            st.download_button(
                "Baixar histórico CSV",
                historico.to_csv(
                    index=False,
                    sep=";"
                ).encode(
                    "ISO-8859-1",
                    errors="replace"
                ),
                "historico.csv",
                "text/csv"
            )
