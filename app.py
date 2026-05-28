# ==========================================
# C XML BR Engine
# COMPLETO + REV + HISTÓRICO + BANCO + REGISTROS
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
from io import BytesIO
from zoneinfo import ZoneInfo
from io import BytesIO
from openpyxl import load_workbook

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
    familia TEXT,
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

cursor.execute("""
CREATE TABLE IF NOT EXISTS registros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_base TEXT,
    fabrica TEXT,
    ce_bri TEXT,
    familia TEXT,
    registro TEXT,
    endereco_fabrica TEXT,
    arquivo_excel TEXT,
    data_cadastro TEXT
)
""")


cursor.execute("""
CREATE TABLE IF NOT EXISTS sistema5_clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    categoria TEXT,
    cliente_base TEXT,
    data_cadastro TEXT,
    UNIQUE(categoria, cliente_base)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS sistema5_fabricas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER,
    fabrica TEXT,
    ce_bri TEXT,
    endereco_fabrica TEXT,
    data_cadastro TEXT,
    UNIQUE(cliente_id, fabrica)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS sistema5_arquivos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER,
    fabrica_id INTEGER,
    tipo_processo TEXT,
    ip_processo TEXT,
    data_processo TEXT,
    arquivo_nome TEXT,
    data_upload TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS sistema5_itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arquivo_id INTEGER,
    cliente_base TEXT,
    categoria TEXT,
    fabrica TEXT,
    ce_bri TEXT,
    endereco_fabrica TEXT,
    tipo_processo TEXT,
    ip_processo TEXT,
    data_processo TEXT,
    familia TEXT,
    item TEXT,
    marca TEXT,
    modelo TEXT,
    nome TEXT,
    codigo TEXT,
    arquivo_nome TEXT,
    data_upload TEXT
)
""")

conn.commit()

# ==========================================
# AJUSTES PARA BANCOS ANTIGOS
# ==========================================

for tabela, coluna, tipo in [
    ("registros", "cliente_base", "TEXT"),
    ("registros", "ce_bri", "TEXT"),
    ("registros", "familia", "TEXT"),
    ("registros", "registro", "TEXT"),
    ("registros", "endereco_fabrica", "TEXT"),
    ("registros", "fabrica", "TEXT"),
    ("registros", "arquivo_excel", "TEXT"),
    ("registros", "data_cadastro", "TEXT"),
    ("certificados", "produto", "TEXT"),
    ("certificados", "ce_bri", "TEXT"),
    ("certificados", "familia", "TEXT"),
    ("certificados", "rev", "INTEGER"),
    ("certificados", "data_emissao", "TEXT"),
    ("certificados", "arquivo_pdf", "TEXT"),
    ("certificados", "data_cadastro", "TEXT"),
    ("certificados", "data_atualizacao", "TEXT"),
    ("itens", "certificado_id", "INTEGER"),
    ("itens", "ordem", "INTEGER"),
    ("itens", "marca", "TEXT"),
    ("itens", "modelo", "TEXT"),
    ("itens", "nome", "TEXT"),
    ("itens", "codigo", "TEXT"),
    ("sistema5_itens", "familia", "TEXT"),
    ("sistema5_itens", "item", "TEXT"),
]:
    try:
        cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
        conn.commit()
    except sqlite3.OperationalError:
        pass

try:
    cursor.execute("UPDATE registros SET cliente_base = 'BOLSA' WHERE cliente_base IS NULL OR cliente_base = ''")
    conn.commit()
except Exception:
    pass

try:
    certificados_sem_familia = cursor.execute("SELECT id, ip_bri FROM certificados WHERE familia IS NULL OR familia = ''").fetchall()
    for cert_id, ip_bri_atual in certificados_sem_familia:
        fam = extrair_familia_ip_bri(ip_bri_atual) if 'extrair_familia_ip_bri' in globals() else None
        if fam:
            cursor.execute("UPDATE certificados SET familia = ? WHERE id = ?", (fam, cert_id))
    conn.commit()
except Exception:
    pass

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
        nome = nome.replace("PRODUZIDO", "PROD.")
        nome = nome.replace("INDICATIVO", "IND.")
        nome = nome.replace("RESTRITIVO", "REST.")
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
        duplicados = duplicados.sort_values(by="CODIGO")

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

    linhas = [clean(l) for l in texto.split("\n") if clean(l)]

    for i, linha in enumerate(linhas):
        if linha.upper() in ["REV", "REV.", "REVISÃO", "REVISAO"] and i + 1 < len(linhas):
            numero = re.sub(r"\D", "", linhas[i + 1])
            if numero:
                return int(numero)

    return 0


# ==========================================
# EXTRAÇÃO CERTIFICADO
# ==========================================


def extrair_familia_ip_bri(ip_bri):
    if not ip_bri:
        return None

    match = re.search(r"-([0-9]+)$", ip_bri)

    if not match:
        return None

    return str(int(match.group(1)))



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
        r"Data de Emissão:\s*(\d{2}\/\d{2}\/\d{4})",
        texto,
        flags=re.IGNORECASE
    )

    if emissao_match:
        data_emissao = emissao_match.group(1)

    rev = extrair_rev(texto)
    familia = extrair_familia_ip_bri(ip_bri)

    return {
        "ip_bri": ip_bri,
        "produto": produto,
        "ce_bri": ce_bri,
        "rev": rev,
        "familia": familia,
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
                f"MARCA: {antigo[1]} | MODELO: {antigo[2]} | NOME: {antigo[3]} | CÓDIGO: {antigo[4]}",
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
                f"MARCA: {novo[1]} | MODELO: {novo[2]} | NOME: {novo[3]} | CÓDIGO: {novo[4]}",
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


def garantir_estrutura_banco():
    # Garante que todas as tabelas principais existam
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
    CREATE TABLE IF NOT EXISTS registros (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_base TEXT,
        fabrica TEXT,
        ce_bri TEXT,
        familia TEXT,
        registro TEXT,
        arquivo_excel TEXT,
        data_cadastro TEXT
    )
    """)

    conn.commit()

    ajustes = [
        ("itens", "certificado_id", "INTEGER"),
        ("itens", "ordem", "INTEGER"),
        ("itens", "marca", "TEXT"),
        ("itens", "modelo", "TEXT"),
        ("itens", "nome", "TEXT"),
        ("itens", "codigo", "TEXT"),
        ("certificados", "produto", "TEXT"),
        ("certificados", "ce_bri", "TEXT"),
        ("certificados", "familia", "TEXT"),
        ("certificados", "rev", "INTEGER"),
        ("certificados", "data_emissao", "TEXT"),
        ("certificados", "arquivo_pdf", "TEXT"),
        ("certificados", "data_cadastro", "TEXT"),
        ("certificados", "data_atualizacao", "TEXT"),
        ("registros", "cliente_base", "TEXT"),
        ("registros", "ce_bri", "TEXT"),
        ("registros", "familia", "TEXT"),
        ("registros", "registro", "TEXT"),
        ("registros", "endereco_fabrica", "TEXT"),
        ("registros", "fabrica", "TEXT"),
        ("registros", "arquivo_excel", "TEXT"),
        ("registros", "data_cadastro", "TEXT"),
    ]

    for tabela, coluna, tipo in ajustes:
        try:
            cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    try:
        cursor.execute("UPDATE registros SET cliente_base = 'BOLSA' WHERE cliente_base IS NULL OR cliente_base = ''")
        conn.commit()
    except Exception:
        pass


def reparar_tabela_itens_se_necessario():
    obrigatorias = {
        "id",
        "certificado_id",
        "ordem",
        "marca",
        "modelo",
        "nome",
        "codigo"
    }

    try:
        info = cursor.execute("PRAGMA table_info(itens)").fetchall()
        existentes = {linha[1] for linha in info}
    except Exception:
        existentes = set()

    if obrigatorias.issubset(existentes):
        return

    # Cria uma tabela nova correta e tenta preservar o que for possível
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS itens_corrigida (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        certificado_id INTEGER,
        ordem INTEGER,
        marca TEXT,
        modelo TEXT,
        nome TEXT,
        codigo TEXT
    )
    """)

    colunas_comuns = [c for c in ["id", "certificado_id", "ordem", "marca", "modelo", "nome", "codigo"] if c in existentes]

    if colunas_comuns:
        cols = ", ".join(colunas_comuns)
        try:
            cursor.execute(f"INSERT OR IGNORE INTO itens_corrigida ({cols}) SELECT {cols} FROM itens")
        except Exception:
            pass

    try:
        cursor.execute("DROP TABLE itens")
    except Exception:
        pass

    cursor.execute("ALTER TABLE itens_corrigida RENAME TO itens")
    conn.commit()


def inserir_item_seguro(certificado_id, r):
    reparar_tabela_itens_se_necessario()

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


def salvar_ou_atualizar_certificado(
    dados_certificado,
    rows,
    nome_arquivo
):
    garantir_estrutura_banco()
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
            familia,
            rev,
            data_emissao,
            arquivo_pdf,
            data_cadastro,
            data_atualizacao
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ip_bri,
            dados_certificado["produto"],
            dados_certificado["ce_bri"],
            dados_certificado.get("familia"),
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

    certificado_id = existente[0]
    rev_antiga = int(existente[1] or 0)

    # Verifica se o certificado existe, mas ficou sem itens no banco.
    # Nesse caso, mesmo com REV igual ou menor, o sistema preenche os itens sem apagar dados úteis.
    qtd_itens_existentes = cursor.execute("""
    SELECT COUNT(*)
    FROM itens
    WHERE certificado_id = ?
    """, (certificado_id,)).fetchone()[0]

    if rev_nova <= rev_antiga and qtd_itens_existentes > 0:
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

        return "ignorado", "REV menor ou igual. Banco não alterado."

    if rev_nova <= rev_antiga and qtd_itens_existentes == 0:
        cursor.execute("""
        UPDATE certificados
        SET
            produto = ?,
            ce_bri = ?,
            familia = ?,
            rev = ?,
            data_emissao = ?,
            arquivo_pdf = ?,
            data_atualizacao = ?
        WHERE id = ?
        """, (
            dados_certificado["produto"],
            dados_certificado["ce_bri"],
            dados_certificado.get("familia"),
            rev_nova,
            dados_certificado["data_emissao"],
            nome_arquivo,
            datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            certificado_id
        ))

        for r in rows:
            inserir_item_seguro(certificado_id, r)

        conn.commit()

        registrar_historico(
            ip_bri,
            rev_antiga,
            rev_nova,
            "",
            "",
            "ITENS_REINSERIDOS",
            "",
            "Certificado existia sem itens vinculados",
            f"{len(rows)} itens inseridos na REV {rev_nova}",
            nome_arquivo
        )

        return "corrigido", f"Certificado já existia, mas estava sem itens. {len(rows)} itens foram inseridos."

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
        familia = ?,
        rev = ?,
        data_emissao = ?,
        arquivo_pdf = ?,
        data_atualizacao = ?
    WHERE id = ?
    """, (
        dados_certificado["produto"],
        dados_certificado["ce_bri"],
        dados_certificado.get("familia"),
        rev_nova,
        dados_certificado["data_emissao"],
        nome_arquivo,
        datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        certificado_id
    ))

    for r in rows:
        inserir_item_seguro(certificado_id, r)

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
# EXPORTAR
# ==========================================


def exportar_todos_itens():
    return pd.read_sql_query("""
    SELECT
        i.marca AS marca,
        i.modelo AS modelo,
        i.nome AS nome,
        i.codigo AS codigo,
        c.ip_bri AS ip_bri,
        c.ce_bri AS ce_bri,
        r.registro AS registro,
        c.familia AS fam,
        r.fabrica AS fabrica,
        c.rev AS rev,
        c.produto AS produto,
        c.data_emissao AS data_emissao,
        i.ordem AS ordem
    FROM itens i
    INNER JOIN certificados c
    ON c.id = i.certificado_id
    LEFT JOIN registros r
    ON UPPER(r.ce_bri) = UPPER(c.ce_bri)
    AND r.familia = c.familia
    ORDER BY i.marca, i.modelo, c.ip_bri, i.ordem
    """, conn)


# ==========================================
# REGISTROS EXCEL
# ==========================================


def normalizar_familia(valor):
    if pd.isna(valor):
        return ""

    texto = str(valor).strip()

    if texto.endswith(".0"):
        texto = texto[:-2]

    numeros = re.findall(r"[0-9]+", texto)

    if numeros:
        return str(int(numeros[0]))

    return ""



def normalizar_registro(valor):
    if pd.isna(valor):
        return ""

    texto = str(valor).strip()

    if texto.endswith(".0"):
        texto = texto[:-2]

    return texto



def parece_registro(valor):
    texto = normalizar_registro(valor)

    if not texto:
        return False

    return bool(re.search(r"[0-9]+[ ]*/[ ]*[0-9]+", texto))



def extrair_ce_bri_da_aba(aba):
    match = re.search(
        r"CE-BRI-[A-Z0-9\-]+",
        str(aba),
        flags=re.IGNORECASE
    )

    if match:
        return match.group(0).upper()

    return None



def ler_registros_aba(excel_file, aba):
    bruto = pd.read_excel(
        excel_file,
        sheet_name=aba,
        header=None,
        dtype=object
    )

    registros = []

    for i, row in bruto.iterrows():
        valores = [str(v).strip().upper() for v in row.values]

        cols_familia = [
            idx for idx, valor in enumerate(valores)
            if "FAMILIA" in valor or "FAMÍLIA" in valor
        ]

        cols_registro = [
            idx for idx, valor in enumerate(valores)
            if "REGISTRO" in valor
        ]

        if not cols_familia or not cols_registro:
            continue

        for col_familia in cols_familia:
            registros_direita = [c for c in cols_registro if c > col_familia]

            if registros_direita:
                col_registro = registros_direita[0]
            else:
                col_registro = min(cols_registro, key=lambda c: abs(c - col_familia))

            for j in range(i + 1, len(bruto)):
                linha_atual = [str(v).strip().upper() for v in bruto.iloc[j].values]
                linha_texto = " ".join([v for v in linha_atual if v and v.lower() != "nan"])

                if ("FAMILIA" in linha_texto or "FAMÍLIA" in linha_texto) and "REGISTRO" in linha_texto:
                    break

                familia_raw = bruto.iat[j, col_familia] if col_familia < bruto.shape[1] else None
                registro_raw = bruto.iat[j, col_registro] if col_registro < bruto.shape[1] else None

                familia = normalizar_familia(familia_raw)
                registro = normalizar_registro(registro_raw)

                if familia and registro and parece_registro(registro):
                    registros.append({
                        "FAMILIA": familia,
                        "REGISTRO": registro,
                        "FABRICA": aba,
                        "CE_BRI": extrair_ce_bri_da_aba(aba)
                    })

    if not registros:
        for i, row in bruto.iterrows():
            for col in range(bruto.shape[1] - 1):
                familia = normalizar_familia(bruto.iat[i, col])
                registro = normalizar_registro(bruto.iat[i, col + 1])

                if familia and registro and parece_registro(registro):
                    registros.append({
                        "FAMILIA": familia,
                        "REGISTRO": registro,
                        "FABRICA": aba,
                        "CE_BRI": extrair_ce_bri_da_aba(aba)
                    })

    if not registros:
        return None

    dados = pd.DataFrame(registros)

    dados = dados.drop_duplicates(
        subset=["FAMILIA", "REGISTRO", "FABRICA", "CE_BRI"]
    )

    dados["FAMILIA_NUM"] = pd.to_numeric(dados["FAMILIA"], errors="coerce")
    dados = dados.sort_values(
        by=["FAMILIA_NUM", "REGISTRO"]
    ).drop(columns=["FAMILIA_NUM"])

    return dados



def salvar_registros_no_banco(banco_registros, arquivo_nome, cliente_base, enderecos_fabricas=None):
    if banco_registros is None or banco_registros.empty:
        return 0

    cliente_base = clean(cliente_base).upper()
    enderecos_fabricas = enderecos_fabricas or {}

    # Apaga somente os registros da base atual.
    # Exemplo: salvar BOLSA não apaga MOHNISH.
    cursor.execute("DELETE FROM registros WHERE UPPER(cliente_base) = UPPER(?)", (cliente_base,))

    total = 0

    for _, r in banco_registros.iterrows():
        fabrica = r.get("FABRICA", "")
        endereco = enderecos_fabricas.get(str(fabrica), "")

        cursor.execute("""
        INSERT INTO registros (
            cliente_base,
            fabrica,
            ce_bri,
            familia,
            registro,
            endereco_fabrica,
            arquivo_excel,
            data_cadastro
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cliente_base,
            fabrica,
            r.get("CE_BRI", ""),
            str(r.get("FAMILIA", "")),
            r.get("REGISTRO", ""),
            endereco,
            arquivo_nome,
            datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        ))
        total += 1

    conn.commit()
    return total


def exportar_registros_banco():
    return pd.read_sql_query("""
    SELECT
        cliente_base,
        fabrica,
        ce_bri,
        familia,
        registro,
        endereco_fabrica,
        arquivo_excel,
        data_cadastro
    FROM registros
    ORDER BY cliente_base, fabrica, CAST(familia AS INTEGER), registro
    """, conn)



def buscar_registro_por_certificado(ce_bri, familia):
    if not ce_bri or not familia:
        return pd.DataFrame()

    return pd.read_sql_query("""
    SELECT
        fabrica,
        ce_bri,
        familia,
        registro,
        endereco_fabrica,
        arquivo_excel,
        data_cadastro
    FROM registros
    WHERE UPPER(ce_bri) = UPPER(?)
    AND familia = ?
    ORDER BY fabrica, familia, registro
    """, conn, params=(ce_bri, str(int(familia))))


def gerar_backup_geral_zip():
    buffer = BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        data_hora = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        if Path(DB_PATH).exists():
            zipf.write(DB_PATH, f"backup_db/certificados_{data_hora}.db")

        try:
            banco_completo = exportar_todos_itens()
            zipf.writestr(
                f"csv/banco_completo_{data_hora}.csv",
                banco_completo.to_csv(index=False, sep=";").encode("ISO-8859-1", errors="replace")
            )
        except Exception:
            pass

        try:
            registros = exportar_registros_banco()
            zipf.writestr(
                f"csv/registros_{data_hora}.csv",
                registros.to_csv(index=False, sep=";").encode("ISO-8859-1", errors="replace")
            )
        except Exception:
            pass

        try:
            certificados = pd.read_sql_query("SELECT * FROM certificados ORDER BY ip_bri", conn)
            zipf.writestr(
                f"csv/certificados_{data_hora}.csv",
                certificados.to_csv(index=False, sep=";").encode("ISO-8859-1", errors="replace")
            )
        except Exception:
            pass

        try:
            itens = pd.read_sql_query("SELECT * FROM itens ORDER BY certificado_id, ordem", conn)
            zipf.writestr(
                f"csv/itens_puros_{data_hora}.csv",
                itens.to_csv(index=False, sep=";").encode("ISO-8859-1", errors="replace")
            )
        except Exception:
            pass

        try:
            historico = pd.read_sql_query("SELECT * FROM historico_alteracoes ORDER BY id DESC", conn)
            zipf.writestr(
                f"csv/historico_{data_hora}.csv",
                historico.to_csv(index=False, sep=";").encode("ISO-8859-1", errors="replace")
            )
        except Exception:
            pass

        try:
            resumo = f"""BACKUP GERAL C XML BR ENGINE
Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

Arquivos incluídos:
- certificados.db
- banco_completo.csv
- registros.csv
- certificados.csv
- itens_puros.csv
- historico.csv
"""
            zipf.writestr("LEIA-ME.txt", resumo.encode("ISO-8859-1", errors="replace"))
        except Exception:
            pass

    buffer.seek(0)
    return buffer



def aviso_backup_diario():
    try:
        hora_sp = datetime.now(ZoneInfo("America/Sao_Paulo")).hour
        if hora_sp >= 18:
            st.sidebar.error("⚠️ Faça o backup geral antes de sair. O Streamlit pode reiniciar e apagar os dados.")
    except Exception:
        pass



def atualizar_familias_certificados():
    try:
        garantir_estrutura_banco()
    except Exception:
        pass

    try:
        certificados = cursor.execute("SELECT id, ip_bri FROM certificados").fetchall()
        for cert_id, ip_bri_atual in certificados:
            fam = extrair_familia_ip_bri(ip_bri_atual)
            if fam:
                cursor.execute("UPDATE certificados SET familia = ? WHERE id = ?", (fam, cert_id))
        conn.commit()
    except Exception:
        pass


atualizar_familias_certificados()

# ==========================================
# PREENCHIMENTO DE CONFIRMAÇÃO
# ==========================================


def cor_rgb(cell):
    try:
        fill = cell.fill
        if fill is None or fill.fill_type is None:
            return None

        color = fill.fgColor

        if color is None:
            return None

        rgb = color.rgb

        if not rgb:
            return None

        rgb = str(rgb).replace("#", "")

        if len(rgb) == 8:
            rgb = rgb[2:]

        if len(rgb) != 6:
            return None

        return tuple(int(rgb[i:i+2], 16) for i in (0, 2, 4))
    except Exception:
        return None



def eh_amarelo(cell):
    rgb = cor_rgb(cell)
    if not rgb:
        return False

    r, g, b = rgb
    return r >= 180 and g >= 150 and b <= 140



def eh_verde(cell):
    rgb = cor_rgb(cell)
    if not rgb:
        return False

    r, g, b = rgb
    return g >= 120 and r <= 180 and b <= 180 and g >= r



def eh_azul(cell):
    rgb = cor_rgb(cell)
    if not rgb:
        return False

    r, g, b = rgb
    return b >= 120 and b > r and b >= g



def normalizar_cabecalho(valor):
    texto = clean(valor).upper()
    texto = texto.replace("CÓDIGO", "CODIGO")
    texto = texto.replace("COD.", "CODIGO")
    texto = texto.replace("CÓD.", "CODIGO")
    texto = texto.replace("IP-BRI", "IP_BRI")
    texto = texto.replace("CE-BRI", "CE_BRI")
    texto = texto.replace("ENDEREÇO", "ENDERECO")
    texto = texto.replace("END.", "ENDERECO")
    texto = texto.replace("ENDERECO_DA_FABRICA", "ENDERECO")
    texto = texto.replace("ENDEREÇO_DA_FABRICA", "ENDERECO")
    texto = texto.replace("ENDERECO_FABRICA", "ENDERECO")
    texto = texto.replace("ENDEREÇO_FABRICA", "ENDERECO")
    texto = texto.replace(" ", "_")
    texto = texto.replace("ENDERECO_DA_FABRICA", "ENDERECO")
    texto = texto.replace("ENDERECO_FABRICA", "ENDERECO")
    return texto



def buscar_item_confirmacao(valor_ref):
    ref = clean(valor_ref)

    if not ref:
        return None

    item_s5 = buscar_item_sistema5_confirmacao(ref)

    if item_s5:
        return item_s5

    resultado = pd.read_sql_query("""
    SELECT
        i.marca AS MARCA,
        i.modelo AS MODELO,
        i.nome AS NOME,
        i.codigo AS CODIGO,
        c.ip_bri AS IP_BRI,
        c.ce_bri AS CE_BRI,
        r.registro AS REGISTRO,
        r.endereco_fabrica AS ENDERECO
    FROM itens i
    INNER JOIN certificados c
    ON c.id = i.certificado_id
    LEFT JOIN registros r
    ON UPPER(r.ce_bri) = UPPER(c.ce_bri)
    AND r.familia = c.familia
    WHERE UPPER(TRIM(i.modelo)) = UPPER(TRIM(?))
       OR UPPER(TRIM(i.modelo)) LIKE UPPER(TRIM(?) || ' -%')
       OR UPPER(TRIM(i.modelo)) LIKE UPPER(TRIM(?) || '%')
    ORDER BY c.rev DESC, c.ip_bri DESC
    LIMIT 1
    """, conn, params=(ref, ref, ref))

    if resultado.empty:
        return None

    return resultado.iloc[0].to_dict()


def descobrir_cabecalho_coluna(ws, row_idx, col_idx):
    # Primeiro procura cabeçalho azul acima da célula amarela
    for r in range(row_idx - 1, 0, -1):
        cell = ws.cell(r, col_idx)
        valor = clean(cell.value)

        if valor and (eh_azul(cell) or normalizar_cabecalho(valor) in ["MARCA", "MODELO", "NOME", "CODIGO", "IP_BRI", "CE_BRI", "REGISTRO", "ENDERECO", "FAMILIA", "ITEM", "TIPO_PROCESSO", "DATA_PROCESSO", "ARQUIVO_ORIGEM"]):
            return normalizar_cabecalho(valor)

    # Plano B: procura qualquer texto de cabeçalho acima
    for r in range(row_idx - 1, 0, -1):
        valor = clean(ws.cell(r, col_idx).value)
        cab = normalizar_cabecalho(valor)

        if cab in ["MARCA", "MODELO", "NOME", "CODIGO", "IP_BRI", "CE_BRI", "REGISTRO", "ENDERECO", "FAMILIA", "ITEM", "TIPO_PROCESSO", "DATA_PROCESSO", "ARQUIVO_ORIGEM"]:
            return cab

    return ""



def preencher_excel_confirmacao(uploaded_file):
    wb = load_workbook(uploaded_file)

    preenchidos = 0
    nao_encontrados = []

    campos_validos = ["MARCA", "MODELO", "NOME", "CODIGO", "IP_BRI", "CE_BRI", "REGISTRO", "ENDERECO", "FAMILIA", "ITEM", "TIPO_PROCESSO", "DATA_PROCESSO", "ARQUIVO_ORIGEM"]

    for ws in wb.worksheets:
        for row in ws.iter_rows():
            refs = []

            # REGRA OFICIAL:
            # Qualquer célula verde da linha é considerada referência.
            # Não importa o nome da coluna.
            # Não precisa existir coluna chamada REF.
            for cell in row:
                if eh_verde(cell) and clean(cell.value):
                    refs.append(clean(cell.value))

            if not refs:
                continue

            item = None

            # Se houver mais de uma célula verde na linha, tenta na ordem em que aparece.
            for ref in refs:
                item = buscar_item_confirmacao(ref)
                if item:
                    break

            if not item:
                nao_encontrados.extend(refs)
                continue

            for cell in row:
                if not eh_amarelo(cell):
                    continue

                campo = descobrir_cabecalho_coluna(ws, cell.row, cell.column)

                if campo not in campos_validos:
                    continue

                valor = item.get(campo)

                if valor is None:
                    continue

                valor = str(valor).strip()

                if valor == "" or valor.lower() == "nan":
                    continue

                cell.value = valor
                preenchidos += 1

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return output, preenchidos, nao_encontrados


def atualizar_endereco_fabrica_existente(cliente_base, fabrica, novo_endereco):
    cliente_base = clean(cliente_base).upper()
    fabrica = clean(fabrica)
    novo_endereco = clean(novo_endereco)

    cursor.execute("""
    UPDATE registros
    SET endereco_fabrica = ?
    WHERE UPPER(cliente_base) = UPPER(?)
    AND fabrica = ?
    """, (
        novo_endereco,
        cliente_base,
        fabrica
    ))

    conn.commit()
    return cursor.rowcount




# ==========================================
# PESQUISA AVANÇADA
# ==========================================

def pesquisar_por_ip_bri(ip_bri_busca):
    termo = clean(ip_bri_busca).upper()

    if not termo:
        return pd.DataFrame()

    termo_sem_prefixo = termo.replace("IP-BRI-", "")
    termo_com_prefixo = termo if termo.startswith("IP-BRI-") else f"IP-BRI-{termo}"

    return pd.read_sql_query("""
    SELECT DISTINCT
        c.ip_bri AS ip_bri,
        c.ce_bri AS ce_bri,
        c.familia AS fam,
        r.registro AS registro,
        r.fabrica AS fabrica,
        r.endereco_fabrica AS endereco,
        c.rev AS rev,
        c.produto AS produto,
        c.data_emissao AS data_emissao
    FROM certificados c
    LEFT JOIN registros r
    ON UPPER(r.ce_bri) = UPPER(c.ce_bri)
    AND r.familia = c.familia
    WHERE UPPER(c.ip_bri) LIKE ?
       OR REPLACE(UPPER(c.ip_bri), 'IP-BRI-', '') LIKE ?
    ORDER BY c.ip_bri, r.fabrica, r.registro
    """, conn, params=(f"{termo_com_prefixo}%", f"{termo_sem_prefixo}%"))


def pesquisar_por_registro(registro_busca):
    termo = clean(registro_busca)

    if not termo:
        return pd.DataFrame()

    return pd.read_sql_query("""
    SELECT
        r.registro AS registro,
        c.ip_bri AS ip_bri,
        c.ce_bri AS ce_bri,
        c.familia AS fam,
        r.fabrica AS fabrica,
        r.endereco_fabrica AS endereco,
        marcas.fabricante AS fabricante,
        c.rev AS rev,
        c.produto AS produto,
        c.data_emissao AS data_emissao
    FROM registros r
    LEFT JOIN certificados c
    ON UPPER(c.ce_bri) = UPPER(r.ce_bri)
    AND c.familia = r.familia
    LEFT JOIN (
        SELECT
            certificado_id,
            MIN(marca) AS fabricante
        FROM itens
        GROUP BY certificado_id
    ) marcas
    ON marcas.certificado_id = c.id
    WHERE r.registro LIKE ?
    ORDER BY r.registro, c.ip_bri, marcas.fabricante
    """, conn, params=(f"{termo}%",))


# ==========================================
# SISTEMA 5 - INCLUSÕES / MANUTENÇÕES
# ==========================================

def normalizar_categoria_sistema5(valor):
    valor = clean(valor).upper()
    if "NOVO" in valor:
        return "SISTEMA 5 NOVO PROJETO"
    if "PROPR" in valor:
        return "SISTEMA 5 PROPRIOS"
    return valor


def extrair_ip_processo(nome):
    texto = clean(nome).upper()
    match = re.search(r"\bIP[- ]?\d+[-/]\d+\b", texto)
    if match:
        return match.group(0).replace(" ", "-")
    return None


def extrair_data_processo(nome):
    texto = clean(nome)
    match = re.search(r"\b(\d{2})[-_.](\d{2})[-_.](\d{2,4})\b", texto)
    if not match:
        return None
    dia, mes, ano = match.groups()
    if len(ano) == 2:
        ano = "20" + ano
    return f"{ano}-{mes}-{dia}"


def detectar_tipo_processo(nome):
    texto = clean(nome).upper()
    if "MANUT" in texto:
        return "MANUTENCAO"
    if "RECERT" in texto:
        return "RECERTIFICACAO"
    if "INICIAL" in texto:
        return "INICIAL"
    if "INCLUS" in texto:
        return "INCLUSAO"
    return "OUTROS"


def get_or_create_cliente_sistema5(categoria, cliente_base):
    categoria = normalizar_categoria_sistema5(categoria)
    cliente_base = clean(cliente_base).upper()

    cursor.execute("""
    INSERT OR IGNORE INTO sistema5_clientes (categoria, cliente_base, data_cadastro)
    VALUES (?, ?, ?)
    """, (categoria, cliente_base, datetime.now().strftime("%d/%m/%Y %H:%M:%S")))
    conn.commit()

    return cursor.execute("""
    SELECT id FROM sistema5_clientes
    WHERE categoria = ? AND cliente_base = ?
    """, (categoria, cliente_base)).fetchone()[0]


def get_or_create_fabrica_sistema5(cliente_id, fabrica, ce_bri="", endereco_fabrica=""):
    fabrica = clean(fabrica).upper()
    ce_bri = clean(ce_bri).upper()
    endereco_fabrica = clean(endereco_fabrica)

    cursor.execute("""
    INSERT OR IGNORE INTO sistema5_fabricas (
        cliente_id, fabrica, ce_bri, endereco_fabrica, data_cadastro
    )
    VALUES (?, ?, ?, ?, ?)
    """, (
        cliente_id,
        fabrica,
        ce_bri,
        endereco_fabrica,
        datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    ))

    cursor.execute("""
    UPDATE sistema5_fabricas
    SET
        ce_bri = COALESCE(NULLIF(?, ''), ce_bri),
        endereco_fabrica = COALESCE(NULLIF(?, ''), endereco_fabrica)
    WHERE cliente_id = ? AND fabrica = ?
    """, (ce_bri, endereco_fabrica, cliente_id, fabrica))

    conn.commit()

    return cursor.execute("""
    SELECT id FROM sistema5_fabricas
    WHERE cliente_id = ? AND fabrica = ?
    """, (cliente_id, fabrica)).fetchone()[0]


def normalizar_coluna_excel_s5(valor):
    txt = clean(valor).upper()

    # Remove acentos para padronizar
    troca = {
        "Á": "A", "À": "A", "Â": "A", "Ã": "A",
        "É": "E", "Ê": "E",
        "Í": "I",
        "Ó": "O", "Ô": "O", "Õ": "O",
        "Ú": "U",
        "Ç": "C"
    }

    for antigo, novo in troca.items():
        txt = txt.replace(antigo, novo)

    # Limpa espaços duplicados
    txt = re.sub(r"\s+", " ", txt).strip()

    # Códigos
    if (
        "CODIGO DE BARRAS" in txt
        or "COD DE BARRAS" in txt
        or "COD. DE BARRAS" in txt
        or txt in ["CODIGO", "COD.", "COD"]
        or "BARRAS" in txt
    ):
        return "CODIGO"

    # Modelo / Referência
    if (
        "MODELO" in txt
        or "REFERENCIA" in txt
        or "DESIGNACAO COMERCIAL" in txt
    ):
        return "MODELO"

    # Marca
    if (
        "MARCA" in txt
        or "MARCA COMERCIALIZADA" in txt
        or "FABRICANTE" in txt
    ):
        return "MARCA"

    # Descrição técnica
    if (
        "DESCRICAO TECNICA" in txt
        or "DESCRICAO TECNICA DO MODELO" in txt
        or "DESCRICAO" in txt
        or "NOME" in txt
        or "PROCESSO PRODUTIVO" in txt
    ):
        return "NOME"

    # Item
    if txt == "ITEM" or txt.startswith("ITEM "):
        return "ITEM"

    return txt


def ler_excel_inclusao_sistema5(uploaded_file):
    """
    Leitor específico do Sistema 5.

    Estrutura esperada:
    - O Excel pode ter várias abas.
    - Cada aba representa uma família.
    - Dentro de cada aba existem as colunas:
      ITEM, MODELO / REFERÊNCIA, MARCA COMERCIALIZADA,
      CÓDIGO DE BARRAS, DESCRIÇÃO TÉCNICA.

    Regras:
    - Só considera linha real se tiver MODELO + MARCA + CÓDIGO + DESCRIÇÃO.
    - Ignora observações, assinaturas, local/data, rodapé e linhas soltas.
    """

    try:
        excel = pd.ExcelFile(uploaded_file)
    except Exception:
        return pd.DataFrame()

    todos_itens = []

    for aba in excel.sheet_names:
        try:
            bruto = pd.read_excel(
                uploaded_file,
                sheet_name=aba,
                header=None,
                dtype=object
            )
        except Exception:
            continue

        if bruto.empty:
            continue

        header_idx = None
        colunas = {}

        for i, row in bruto.iterrows():
            temp = {}

            for idx, valor in enumerate(row.values):
                nome = normalizar_coluna_excel_s5(valor)

                if nome == "ITEM":
                    temp["ITEM"] = idx
                elif nome == "MODELO":
                    temp["MODELO"] = idx
                elif nome == "MARCA":
                    temp["MARCA"] = idx
                elif nome == "CODIGO":
                    temp["CODIGO"] = idx
                elif nome == "NOME":
                    temp["NOME"] = idx

            # Cabeçalho real precisa ter os campos centrais.
            if all(campo in temp for campo in ["MODELO", "MARCA", "CODIGO", "NOME"]):
                header_idx = i
                colunas = temp
                break

        if header_idx is None:
            continue

        for j in range(header_idx + 1, len(bruto)):
            row = bruto.iloc[j]

            def valor_coluna(nome_coluna):
                idx = colunas.get(nome_coluna)
                if idx is None or idx >= len(row):
                    return ""
                return clean(row.iloc[idx])

            item = valor_coluna("ITEM")
            modelo = valor_coluna("MODELO")
            marca = valor_coluna("MARCA")
            codigo_raw = valor_coluna("CODIGO")
            nome = valor_coluna("NOME")

            codigo = extrair_codigo_unico(codigo_raw) or re.sub(r"\D", "", codigo_raw)

            linha_texto = " ".join([modelo, marca, codigo_raw, nome]).upper()

            palavras_ignorar = [
                "OBS",
                "OBSERVAÇÃO",
                "OBSERVACAO",
                "LOCAL E DATA",
                "PLACE AND DATE",
                "ASSINATURA",
                "SIGNATURE",
                "RESPONSÁVEL",
                "RESPONSAVEL",
                "APROVAÇÃO",
                "APROVACAO"
            ]

            if any(p in linha_texto for p in palavras_ignorar):
                continue

            # Linha real precisa ter os 4 campos principais.
            if not modelo or not marca or not codigo or not nome:
                continue

            # Evita cabeçalho repetido
            if normalizar_coluna_excel_s5(modelo) == "MODELO":
                continue

            if normalizar_coluna_excel_s5(marca) == "MARCA":
                continue

            todos_itens.append({
                "FAMILIA": normalizar_familia_aba_s5(aba),
                "ITEM": item,
                "MARCA": marca,
                "MODELO": modelo,
                "NOME": nome,
                "CODIGO": codigo
            })

    if not todos_itens:
        return pd.DataFrame()

    df_final = pd.DataFrame(todos_itens)

    df_final = df_final.drop_duplicates(
        subset=["FAMILIA", "MODELO", "CODIGO"],
        keep="first"
    )

    return df_final


def salvar_inclusao_sistema5(categoria, cliente_base, fabrica, ce_bri, endereco_fabrica, tipo_processo, ip_processo, data_processo, arquivo_nome, df_itens):
    categoria = normalizar_categoria_sistema5(categoria)
    cliente_base = clean(cliente_base).upper()
    fabrica = clean(fabrica).upper()
    ce_bri = clean(ce_bri).upper()
    endereco_fabrica = clean(endereco_fabrica)
    tipo_processo = clean(tipo_processo).upper()
    ip_processo = clean(ip_processo).upper()

    cliente_id = get_or_create_cliente_sistema5(categoria, cliente_base)
    fabrica_id = get_or_create_fabrica_sistema5(cliente_id, fabrica, ce_bri, endereco_fabrica)

    cursor.execute("""
    INSERT INTO sistema5_arquivos (
        cliente_id, fabrica_id, tipo_processo, ip_processo, data_processo, arquivo_nome, data_upload
    )
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        cliente_id,
        fabrica_id,
        tipo_processo,
        ip_processo,
        data_processo,
        arquivo_nome,
        datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    ))
    conn.commit()
    arquivo_id = cursor.lastrowid

    total = 0

    for _, r in df_itens.iterrows():
        cursor.execute("""
        INSERT INTO sistema5_itens (
            arquivo_id, cliente_base, categoria, fabrica, ce_bri, endereco_fabrica,
            tipo_processo, ip_processo, data_processo, familia, item, marca, modelo, nome, codigo,
            arquivo_nome, data_upload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            arquivo_id,
            cliente_base,
            categoria,
            fabrica,
            ce_bri,
            endereco_fabrica,
            tipo_processo,
            ip_processo,
            data_processo,
            clean(r.get("FAMILIA", "")),
            clean(r.get("ITEM", "")),
            clean(r.get("MARCA", "")),
            clean(r.get("MODELO", "")),
            clean(r.get("NOME", "")),
            clean(r.get("CODIGO", "")),
            arquivo_nome,
            datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        ))
        total += 1

    conn.commit()
    return total


def buscar_item_sistema5_confirmacao(valor_ref):
    ref = clean(valor_ref)

    if not ref:
        return None

    resultado = pd.read_sql_query("""
    SELECT
        marca AS MARCA,
        modelo AS MODELO,
        nome AS NOME,
        codigo AS CODIGO,
        ip_processo AS IP_BRI,
        ce_bri AS CE_BRI,
        NULL AS REGISTRO,
        endereco_fabrica AS ENDERECO,
        fabrica AS FABRICA,
        tipo_processo AS TIPO_PROCESSO,
        data_processo AS DATA_PROCESSO,
        familia AS FAMILIA,
        arquivo_nome AS ARQUIVO_ORIGEM
    FROM sistema5_itens
    WHERE UPPER(TRIM(modelo)) = UPPER(TRIM(?))
       OR UPPER(TRIM(modelo)) LIKE UPPER(TRIM(?) || ' -%')
       OR UPPER(TRIM(modelo)) LIKE UPPER(TRIM(?) || '%')
    ORDER BY COALESCE(data_processo, '1900-01-01') DESC, id DESC
    LIMIT 1
    """, conn, params=(ref, ref, ref))

    if resultado.empty:
        return None

    item = resultado.iloc[0].to_dict()
    ce_bri = item.get("CE_BRI")

    if ce_bri:
        registro_complementar = pd.read_sql_query("""
        SELECT registro
        FROM registros
        WHERE UPPER(ce_bri) = UPPER(?)
        ORDER BY id DESC
        LIMIT 1
        """, conn, params=(ce_bri,))

        if not registro_complementar.empty:
            item["REGISTRO"] = registro_complementar.iloc[0]["registro"]

    return item


def listar_sistema5_resumo():
    return pd.read_sql_query("""
    SELECT
        c.categoria,
        c.cliente_base,
        f.fabrica,
        f.ce_bri,
        f.endereco_fabrica,
        a.tipo_processo,
        a.ip_processo,
        a.data_processo,
        a.arquivo_nome,
        COUNT(i.id) AS qtd_itens
    FROM sistema5_clientes c
    LEFT JOIN sistema5_fabricas f ON f.cliente_id = c.id
    LEFT JOIN sistema5_arquivos a ON a.fabrica_id = f.id
    LEFT JOIN sistema5_itens i ON i.arquivo_id = a.id
    GROUP BY c.categoria, c.cliente_base, f.fabrica, f.ce_bri, f.endereco_fabrica,
             a.tipo_processo, a.ip_processo, a.data_processo, a.arquivo_nome
    ORDER BY c.categoria, c.cliente_base, f.fabrica, a.data_processo DESC
    """, conn)


def buscar_dados_fabrica_existente(cliente_base="", fabrica="", ce_bri=""):
    cliente_base = clean(cliente_base).upper()
    fabrica = clean(fabrica)
    ce_bri = clean(ce_bri).upper()

    where = []
    params = []

    if cliente_base:
        where.append("UPPER(cliente_base) = UPPER(?)")
        params.append(cliente_base)

    if fabrica:
        where.append("UPPER(fabrica) = UPPER(?)")
        params.append(fabrica)

    if ce_bri:
        where.append("UPPER(ce_bri) = UPPER(?)")
        params.append(ce_bri)

    if not where:
        return None

    sql = f"""
    SELECT
        cliente_base,
        fabrica,
        ce_bri,
        endereco_fabrica
    FROM registros
    WHERE {" AND ".join(where)}
    ORDER BY id DESC
    LIMIT 1
    """

    resultado = pd.read_sql_query(sql, conn, params=tuple(params))

    if resultado.empty:
        return None

    return resultado.iloc[0].to_dict()


def listar_fabricas_existentes_para_sistema5(cliente_base=""):
    cliente_base = clean(cliente_base).upper()

    if cliente_base:
        return pd.read_sql_query("""
        SELECT DISTINCT
            fabrica,
            ce_bri,
            endereco_fabrica
        FROM registros
        WHERE UPPER(cliente_base) = UPPER(?)
        AND fabrica IS NOT NULL
        AND fabrica != ''
        ORDER BY fabrica
        """, conn, params=(cliente_base,))

    return pd.read_sql_query("""
    SELECT DISTINCT
        cliente_base,
        fabrica,
        ce_bri,
        endereco_fabrica
    FROM registros
    WHERE fabrica IS NOT NULL
    AND fabrica != ''
    ORDER BY cliente_base, fabrica
    """, conn)


def extrair_codigo_fabrica_nome(nome):
    texto = clean(nome).upper()
    match = re.search(r"\bF\s*0*(\d{1,3})\b", texto)
    if match:
        numero = int(match.group(1))
        return f"F{numero:02d}"
    return ""


def normalizar_familia_aba_s5(nome_aba):
    texto = clean(nome_aba).upper()
    numeros = re.findall(r"\d+", texto)
    if numeros:
        return str(int(numeros[0]))
    return texto


def buscar_fabrica_por_codigo_s5(cliente_base, codigo_fabrica):
    cliente_base = clean(cliente_base).upper()
    codigo_fabrica = clean(codigo_fabrica).upper()

    if not cliente_base or not codigo_fabrica:
        return None

    numero = re.sub(r"\D", "", codigo_fabrica)
    if numero:
        numero_int = str(int(numero))
        codigo_padrao = f"F{int(numero):02d}"
    else:
        numero_int = ""
        codigo_padrao = codigo_fabrica

    resultado = pd.read_sql_query("""
    SELECT
        cliente_base,
        fabrica,
        ce_bri,
        endereco_fabrica
    FROM registros
    WHERE UPPER(cliente_base) = UPPER(?)
    AND (
        UPPER(fabrica) LIKE ?
        OR UPPER(fabrica) LIKE ?
        OR UPPER(fabrica) LIKE ?
    )
    ORDER BY id DESC
    LIMIT 1
    """, conn, params=(
        cliente_base,
        f"%{codigo_padrao}%",
        f"%F{numero_int}%" if numero_int else f"%{codigo_fabrica}%",
        f"%FÁBRICA {numero_int}%" if numero_int else f"%{codigo_fabrica}%"
    ))

    if resultado.empty:
        return None

    return resultado.iloc[0].to_dict()

# ==========================================
# TABS
# ==========================================

aviso_backup_diario()

try:
    st.sidebar.header("Backup Geral")
    st.sidebar.download_button(
        "⬇️ BAIXAR BACKUP GERAL ZIP",
        gerar_backup_geral_zip(),
        "backup_geral_c_xml_br_engine.zip",
        "application/zip",
        key="backup_geral_sidebar"
    )
except Exception as e:
    st.sidebar.warning(f"Backup geral indisponível: {e}")

aba1, aba2, aba3, aba4, aba5, aba6 = st.tabs([
    "PDF → XML",
    "Banco de Certificados",
    "Registros",
    "Preenchimento de Confirmação",
    "Pesquisa Avançada",
    "Sistema 5"
])

# ==========================================
# ABA 1 - XML
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
            pdf_path.write_bytes(uploaded_file.read())

            rows = parse_pdf(pdf_path)

            if not rows:
                st.error("Nenhum item encontrado")
                st.stop()

            dados_certificado = extrair_dados_certificado(pdf_path)

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
IP-BRI: {dados_certificado['ip_bri']}

CE-BRI: {dados_certificado['ce_bri']}

FAMÍLIA: {dados_certificado.get('familia')}

REV: {dados_certificado['rev']}
"""
            )

            registro_vinculado = buscar_registro_por_certificado(
                dados_certificado.get("ce_bri"),
                dados_certificado.get("familia")
            )

            if registro_vinculado.empty:
                st.warning("Nenhum registro vinculado encontrado para este CE-BRI + FAMÍLIA.")
            else:
                st.success("Registro vinculado encontrado ✅")
                st.dataframe(registro_vinculado, use_container_width=True)

            duplicados = verificar_codigos_duplicados(df)

            if not duplicados.empty:
                st.warning("Foram encontrados códigos duplicados neste PDF.")
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
            else:
                st.error(mensagem)

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
# ABA 2 - BANCO
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

    todos = exportar_todos_itens()

    if todos.empty:
        st.info("Nenhum item cadastrado ainda.")
    else:
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

    st.subheader("Enviar certificado para o banco")

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

            col1, col2, col3, col4, col5, col6 = st.columns(6)

            col1.metric("IP-BRI", dados_certificado["ip_bri"] or "Não encontrado")
            col2.metric("CE-BRI", dados_certificado["ce_bri"] or "Não encontrado")
            col3.metric("FAM", dados_certificado.get("familia") or "Não encontrada")
            col4.metric("REV", dados_certificado["rev"])
            col5.metric("Produto", dados_certificado["produto"] or "Não encontrado")
            col6.metric("Emissão", dados_certificado["data_emissao"] or "Não encontrado")

            registro_vinculado = buscar_registro_por_certificado(
                dados_certificado.get("ce_bri"),
                dados_certificado.get("familia")
            )

            if registro_vinculado.empty:
                st.warning("Nenhum registro vinculado encontrado para este CE-BRI + FAMÍLIA.")
            else:
                st.success("Registro vinculado encontrado ✅")
                st.dataframe(registro_vinculado, use_container_width=True)

            if rows:
                df_preview = pd.DataFrame(
                    rows,
                    columns=[
                        "ORDEM",
                        "MARCA",
                        "MODELO",
                        "NOME",
                        "CODIGO"
                    ]
                )

                st.dataframe(df_preview, use_container_width=True)

                duplicados = verificar_codigos_duplicados(df_preview)

                if not duplicados.empty:
                    st.warning("Foram encontrados códigos duplicados.")
                    st.dataframe(duplicados, use_container_width=True)

                if st.button("Salvar / Atualizar banco"):
                    status, mensagem = salvar_ou_atualizar_certificado(
                        dados_certificado,
                        rows,
                        banco_file.name
                    )

                    if status in ["novo", "atualizado"]:
                        st.success(mensagem)
                    elif status == "ignorado":
                        st.info(mensagem)
                    else:
                        st.error(mensagem)

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
            i.marca AS marca,
            i.modelo AS modelo,
            i.nome AS nome,
            i.codigo AS codigo,
            c.ip_bri AS ip_bri,
            c.ce_bri AS ce_bri,
            r.registro AS registro,
            c.familia AS fam,
            r.fabrica AS fabrica,
            c.rev AS rev,
            c.produto AS produto,
            c.data_emissao AS data_emissao,
            i.ordem AS ordem
        FROM itens i
        INNER JOIN certificados c
        ON c.id = i.certificado_id
        LEFT JOIN registros r
        ON UPPER(r.ce_bri) = UPPER(c.ce_bri)
        AND r.familia = c.familia
        WHERE {campo} LIKE ?
        ORDER BY i.marca, i.modelo, c.ip_bri, i.ordem
        """, conn, params=(f"%{termo_busca}%",))

        if resultado_item.empty:
            st.warning("Nenhum item encontrado.")
        else:
            st.success("Item encontrado ✅")
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

    st.subheader("Itens Repetidos")

    if st.button("Ver itens repetidos"):
        itens_repetidos = pd.read_sql_query("""
        SELECT
            i.marca AS marca,
            i.modelo AS modelo,
            i.nome AS nome,
            i.codigo AS codigo,
            c.ip_bri AS ip_bri,
            c.ce_bri AS ce_bri,
            r.registro AS registro,
            c.familia AS fam,
            r.fabrica AS fabrica,
            c.rev AS rev,
            c.produto AS produto,
            c.data_emissao AS data_emissao,
            i.ordem AS ordem
        FROM itens i
        INNER JOIN certificados c
        ON c.id = i.certificado_id
        LEFT JOIN registros r
        ON UPPER(r.ce_bri) = UPPER(c.ce_bri)
        AND r.familia = c.familia
        WHERE i.codigo IN (
            SELECT codigo
            FROM itens
            WHERE codigo IS NOT NULL
            AND codigo != ''
            GROUP BY codigo
            HAVING COUNT(*) > 1
        )
        ORDER BY i.codigo, i.marca, i.modelo
        """, conn)

        if itens_repetidos.empty:
            st.success("Nenhum item repetido encontrado ✅")
        else:
            st.warning("Itens repetidos encontrados.")
            st.dataframe(itens_repetidos, use_container_width=True)

            st.download_button(
                "Baixar itens repetidos em CSV",
                itens_repetidos.to_csv(index=False, sep=";").encode(
                    "ISO-8859-1",
                    errors="replace"
                ),
                "itens_repetidos.csv",
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

    if marcas_banco.empty:
        st.info("Nenhuma marca cadastrada.")
    else:
        marca_filtro = st.selectbox(
            "Selecione uma marca",
            marcas_banco["marca"].tolist(),
            key="marca_filtro"
        )

        resultado_marca = pd.read_sql_query("""
        SELECT
            i.marca AS marca,
            i.modelo AS modelo,
            i.nome AS nome,
            i.codigo AS codigo,
            c.ip_bri AS ip_bri,
            c.ce_bri AS ce_bri,
            r.registro AS registro,
            c.familia AS fam,
            r.fabrica AS fabrica,
            c.rev AS rev,
            c.produto AS produto,
            c.data_emissao AS data_emissao,
            i.ordem AS ordem
        FROM itens i
        INNER JOIN certificados c
        ON c.id = i.certificado_id
        LEFT JOIN registros r
        ON UPPER(r.ce_bri) = UPPER(c.ce_bri)
        AND r.familia = c.familia
        WHERE i.marca = ?
        ORDER BY i.modelo, c.ip_bri
        """, conn, params=(marca_filtro,))

        st.dataframe(resultado_marca, use_container_width=True)

        st.download_button(
            "Baixar CSV da marca",
            resultado_marca.to_csv(index=False, sep=";").encode(
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

            for (rev_antiga, rev_nova, arquivo_pdf, data_hora), grupo in grupos:
                with st.expander(
                    f"REV {rev_antiga} → REV {rev_nova} | {data_hora} | {arquivo_pdf}"
                ):
                    col1, col2, col3 = st.columns(3)

                    col1.metric(
                        "Itens novos",
                        len(grupo[grupo["tipo_alteracao"] == "ITEM_NOVO"])
                    )

                    col2.metric(
                        "Itens removidos",
                        len(grupo[grupo["tipo_alteracao"] == "ITEM_REMOVIDO"])
                    )

                    col3.metric(
                        "Campos alterados",
                        len(grupo[grupo["tipo_alteracao"] == "CAMPO_ALTERADO"])
                    )

                    for _, row in grupo.iterrows():
                        tipo = row["tipo_alteracao"]

                        if tipo == "CERTIFICADO_NOVO":
                            st.info(f"📄 Certificado novo: {row['valor_novo']}")

                        elif tipo == "CERTIFICADO_ATUALIZADO":
                            st.success(f"🔄 Atualizado: {row['valor_antigo']} → {row['valor_novo']}")

                        elif tipo == "REV_IGNORADA":
                            st.warning(f"⚠️ Revisão ignorada: {row['valor_antigo']} | {row['valor_novo']}")

                        elif tipo == "ITEM_REMOVIDO":
                            st.error(
                                f"🗑️ ITEM REMOVIDO\n\n"
                                f"Modelo: {row['modelo']}\n\n"
                                f"Código: {row['codigo']}\n\n"
                                f"Antes: {row['valor_antigo']}"
                            )

                        elif tipo == "ITEM_NOVO":
                            st.success(
                                f"➕ ITEM NOVO\n\n"
                                f"Modelo: {row['modelo']}\n\n"
                                f"Código: {row['codigo']}\n\n"
                                f"Novo: {row['valor_novo']}"
                            )

                        elif tipo == "CAMPO_ALTERADO":
                            st.warning(
                                f"✏️ CAMPO ALTERADO\n\n"
                                f"Modelo: {row['modelo']}\n\n"
                                f"Código: {row['codigo']}\n\n"
                                f"Campo: {row['campo_alterado']}\n\n"
                                f"Antes: {row['valor_antigo']}\n\n"
                                f"Depois: {row['valor_novo']}"
                            )

            st.download_button(
                "Baixar histórico CSV",
                historico.to_csv(index=False, sep=";").encode(
                    "ISO-8859-1",
                    errors="replace"
                ),
                "historico.csv",
                "text/csv"
            )

# ==========================================
# ABA 3 - REGISTROS
# ==========================================

with aba3:
    st.title("Registros")

    st.subheader("Enviar Excel de Registros")

    cliente_base = st.text_input(
        "Nome da Base / Cliente",
        value="BOLSA",
        key="cliente_base_registros"
    )

    st.info(
        "Envie o Excel de registros. Cada aba será tratada como uma fábrica. "
        "Depois de enviar, você poderá nomear cada fábrica antes de salvar no banco."
    )

    registro_excel = st.file_uploader(
        "Envie o Excel de Registros",
        type=["xlsx", "xls"],
        key="excel_registros"
    )

    if registro_excel:
        try:
            excel = pd.ExcelFile(registro_excel)
            abas = excel.sheet_names

            st.success(f"{len(abas)} abas encontradas ✅")

            st.subheader("Nomear Fábricas")
            st.caption("Se quiser, altere o nome de cada fábrica antes de salvar. Exemplo: F01 - MOHNISH / CE-BRI-XXXX")

            nomes_fabricas = {}
            enderecos_fabricas_por_aba = {}

            for aba in abas:
                nome_sugerido = str(aba)

                nomes_fabricas[aba] = st.text_input(
                    f"Nome da fábrica para a aba: {aba}",
                    value=nome_sugerido,
                    key=f"nome_fabrica_{cliente_base}_{aba}"
                )

                enderecos_fabricas_por_aba[aba] = st.text_area(
                    f"Endereço da fábrica para a aba: {aba}",
                    value="",
                    key=f"endereco_fabrica_{cliente_base}_{aba}",
                    height=80
                )

            todas_fabricas = []

            for aba in abas:
                df_filtrado = ler_registros_aba(
                    registro_excel,
                    aba
                )

                if df_filtrado is None or df_filtrado.empty:
                    continue

                nome_final_fabrica = clean(nomes_fabricas.get(aba, aba)) or str(aba)
                endereco_final_fabrica = clean(enderecos_fabricas_por_aba.get(aba, ""))

                # Mantém o CE-BRI extraído da aba original, mas salva a fábrica com o nome escolhido.
                df_filtrado["FABRICA"] = nome_final_fabrica
                df_filtrado["ENDERECO_FABRICA"] = endereco_final_fabrica

                st.subheader(f"Prévia: {cliente_base} → {nome_final_fabrica}")

                st.dataframe(
                    df_filtrado,
                    use_container_width=True
                )

                todas_fabricas.append(df_filtrado)

            if todas_fabricas:
                banco_registros = pd.concat(
                    todas_fabricas,
                    ignore_index=True
                )

                st.divider()

                st.subheader("Banco Geral de Registros que será salvo")

                st.dataframe(
                    banco_registros,
                    use_container_width=True
                )

                if st.button("Salvar registros desta base", key="salvar_registros_base"):
                    enderecos_para_salvar = {}
                    if "ENDERECO_FABRICA" in banco_registros.columns:
                        for _, linha_endereco in banco_registros.drop_duplicates(subset=["FABRICA"]).iterrows():
                            enderecos_para_salvar[str(linha_endereco.get("FABRICA", ""))] = clean(linha_endereco.get("ENDERECO_FABRICA", ""))

                    total_salvo = salvar_registros_no_banco(
                        banco_registros,
                        registro_excel.name,
                        cliente_base,
                        enderecos_para_salvar
                    )

                    st.success(f"{total_salvo} registros salvos no banco para a base {cliente_base} ✅")

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

            else:
                st.warning("Nenhum registro válido encontrado no Excel.")

        except Exception as e:
            st.error(f"Erro ao ler Excel: {e}")

    st.divider()

    st.subheader("Backup dos Registros / Banco")

    backup_registro_upload = st.file_uploader(
        "Importar backup certificados.db",
        type=["db"],
        key="backup_db_registros"
    )

    if backup_registro_upload:
        conn.close()

        with open(DB_PATH, "wb") as f:
            f.write(backup_registro_upload.read())

        st.success("Backup importado com sucesso. Recarregue o app.")
        st.stop()

    if Path(DB_PATH).exists():
        with open(DB_PATH, "rb") as f:
            st.download_button(
                "Baixar backup atualizado",
                f,
                "certificados.db",
                "application/octet-stream",
                key="download_backup_registros"
            )

    registros_salvos = exportar_registros_banco()

    if not registros_salvos.empty:
        st.download_button(
            "Baixar registros salvos CSV",
            registros_salvos.to_csv(index=False, sep=";").encode(
                "ISO-8859-1",
                errors="replace"
            ),
            "registros_salvos.csv",
            "text/csv",
            key="download_registros_salvos"
        )

    st.divider()

    st.subheader("Visualizar Bases")

    bases_existentes = pd.read_sql_query("""
    SELECT DISTINCT cliente_base
    FROM registros
    WHERE cliente_base IS NOT NULL
    AND cliente_base != ''
    ORDER BY cliente_base
    """, conn)

    if bases_existentes.empty:
        st.info("Nenhuma base salva ainda.")
    else:
        base_selecionada = st.selectbox(
            "Selecione a base",
            bases_existentes["cliente_base"].tolist(),
            key="visualizar_base"
        )

        registros_base = pd.read_sql_query("""
        SELECT
            cliente_base,
            fabrica,
            ce_bri,
            familia,
            registro,
            endereco_fabrica
        FROM registros
        WHERE cliente_base = ?
        ORDER BY fabrica, CAST(familia AS INTEGER)
        """, conn, params=(base_selecionada,))

        fabricas = registros_base["fabrica"].unique().tolist()

        for fabrica in fabricas:
            bloco = registros_base[
                registros_base["fabrica"] == fabrica
            ]

            with st.expander(f"{base_selecionada} → {fabrica}", expanded=False):
                st.dataframe(
                    bloco[[
                        "familia",
                        "registro",
                        "ce_bri",
                        "endereco_fabrica"
                    ]],
                    use_container_width=True
                )

                st.download_button(
                    f"Baixar CSV - {fabrica}",
                    bloco.to_csv(index=False, sep=";").encode(
                        "ISO-8859-1",
                        errors="replace"
                    ),
                    f"{base_selecionada}_{str(fabrica).replace('/', '-')}.csv",
                    "text/csv",
                    key=f"download_{base_selecionada}_{fabrica}"
                )


    st.divider()

    st.subheader("Editar endereço de fábrica já salva")

    bases_para_editar = pd.read_sql_query("""
    SELECT DISTINCT cliente_base
    FROM registros
    WHERE cliente_base IS NOT NULL
    AND cliente_base != ''
    ORDER BY cliente_base
    """, conn)

    if bases_para_editar.empty:
        st.info("Nenhuma base disponível para edição de endereço.")
    else:
        base_editar = st.selectbox(
            "Base / Cliente para editar endereço",
            bases_para_editar["cliente_base"].tolist(),
            key="editar_endereco_base"
        )

        fabricas_para_editar = pd.read_sql_query("""
        SELECT
            fabrica,
            MAX(ce_bri) AS ce_bri,
            MAX(endereco_fabrica) AS endereco_fabrica
        FROM registros
        WHERE cliente_base = ?
        GROUP BY fabrica
        ORDER BY fabrica
        """, conn, params=(base_editar,))

        if fabricas_para_editar.empty:
            st.info("Nenhuma fábrica encontrada nessa base.")
        else:
            opcoes_fabricas = fabricas_para_editar["fabrica"].tolist()

            fabrica_editar = st.selectbox(
                "Fábrica para editar endereço",
                opcoes_fabricas,
                key="editar_endereco_fabrica"
            )

            linha_fabrica = fabricas_para_editar[
                fabricas_para_editar["fabrica"] == fabrica_editar
            ].iloc[0]

            st.caption(f"CE-BRI vinculado: {linha_fabrica.get('ce_bri', '')}")

            endereco_atual = linha_fabrica.get("endereco_fabrica", "")

            if pd.isna(endereco_atual):
                endereco_atual = ""

            novo_endereco = st.text_area(
                "Endereço da fábrica",
                value=str(endereco_atual),
                height=120,
                key="editar_endereco_texto"
            )

            if st.button("Salvar endereço desta fábrica", key="salvar_endereco_fabrica_existente"):
                total_alterado = atualizar_endereco_fabrica_existente(
                    base_editar,
                    fabrica_editar,
                    novo_endereco
                )

                st.success(f"Endereço atualizado em {total_alterado} registros da fábrica {fabrica_editar} ✅")


# ==========================================
# ABA 4 - PREENCHIMENTO DE CONFIRMAÇÃO
# ==========================================

with aba4:
    st.title("Preenchimento de Confirmação")

    st.info(
        "Envie o Excel de confirmação. Qualquer célula verde será tratada como referência, "
        "sem precisar de coluna chamada REF. A busca será feita SOMENTE no campo MODELO do banco. "
        "As células amarelas serão preenchidas conforme o cabeçalho azul da coluna."
    )

    arquivo_confirmacao = st.file_uploader(
        "Envie o Excel de confirmação",
        type=["xlsx", "xlsm"],
        key="excel_confirmacao"
    )

    if arquivo_confirmacao:
        try:
            saida_excel, total_preenchidos, nao_encontrados = preencher_excel_confirmacao(
                arquivo_confirmacao
            )

            st.success(f"Preenchimento concluído ✅ {total_preenchidos} células preenchidas.")

            if nao_encontrados:
                st.warning("Algumas referências verdes não foram encontradas no banco.")
                st.dataframe(
                    pd.DataFrame({"referencia_nao_encontrada": sorted(set(nao_encontrados))}),
                    use_container_width=True
                )

            st.download_button(
                "Baixar Excel preenchido",
                saida_excel,
                "confirmacao_preenchida.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        except Exception as e:
            st.error(f"Erro ao preencher Excel: {e}")


# ==========================================
# ABA 5 - PESQUISA AVANÇADA
# ==========================================

with aba5:
    st.title("Pesquisa Avançada")

    st.info(
        "Use esta aba para cruzar IP-BRI, registro, fábrica e endereço. "
        "Você pode pesquisar pelo IP-BRI para descobrir o registro, ou pesquisar pelo registro para descobrir o IP-BRI."
    )

    tipo_pesquisa_avancada = st.radio(
        "O que você quer pesquisar?",
        [
            "Quero saber o REGISTRO de um IP-BRI",
            "Quero saber o IP-BRI de um REGISTRO"
        ],
        key="tipo_pesquisa_avancada"
    )

    if tipo_pesquisa_avancada == "Quero saber o REGISTRO de um IP-BRI":
        ip_pesquisa = st.text_input(
            "Digite o IP-BRI",
            placeholder="Ex: IP-BRI-0533/2023-15 ou 0533/2023-15",
            key="pesquisa_avancada_ip"
        )

        if ip_pesquisa:
            resultado_ip = pesquisar_por_ip_bri(ip_pesquisa)

            if resultado_ip.empty:
                st.warning("Nenhum registro encontrado para este IP-BRI.")
            else:
                st.success(f"{len(resultado_ip)} resultado(s) encontrado(s) ✅")
                st.dataframe(resultado_ip, use_container_width=True)

                st.download_button(
                    "Baixar resultado em CSV",
                    resultado_ip.to_csv(index=False, sep=";").encode(
                        "ISO-8859-1",
                        errors="replace"
                    ),
                    "pesquisa_por_ip_bri.csv",
                    "text/csv",
                    key="download_pesquisa_ip_bri"
                )

    else:
        registro_pesquisa = st.text_input(
            "Digite o REGISTRO",
            placeholder="Ex: 003889/2023",
            key="pesquisa_avancada_registro"
        )

        if registro_pesquisa:
            resultado_registro = pesquisar_por_registro(registro_pesquisa)

            if resultado_registro.empty:
                st.warning("Nenhum IP-BRI encontrado para este registro.")
            else:
                st.success(f"{len(resultado_registro)} resultado(s) encontrado(s) ✅")
                st.dataframe(resultado_registro, use_container_width=True)

                st.download_button(
                    "Baixar resultado em CSV",
                    resultado_registro.to_csv(index=False, sep=";").encode(
                        "ISO-8859-1",
                        errors="replace"
                    ),
                    "pesquisa_por_registro.csv",
                    "text/csv",
                    key="download_pesquisa_registro"
                )

# ==========================================
# ABA 6 - SISTEMA 5
# ==========================================

with aba6:
    st.title("Sistema 5")

    st.info(
        "Módulo de teste para processos mais recentes que o certificado oficial. "
        "Somente arquivos com IP no nome serão considerados. MODELO/REFERÊNCIA será tratado como MODELO, e cada aba do Excel será tratada como família pelo número da aba."
    )

    categoria_s5 = st.radio(
        "Categoria",
        ["SISTEMA 5 NOVO PROJETO", "SISTEMA 5 PROPRIOS"],
        horizontal=True,
        key="s5_categoria"
    )

    cliente_s5 = st.text_input(
        "Cliente / Solicitante",
        value="BOLSA" if categoria_s5 == "SISTEMA 5 NOVO PROJETO" else "",
        key="s5_cliente"
    )

    st.subheader("Fábrica")

    fabricas_existentes_s5 = listar_fabricas_existentes_para_sistema5(cliente_s5)

    usar_fabrica_existente = False

    if not fabricas_existentes_s5.empty:
        usar_fabrica_existente = st.checkbox(
            "Usar fábrica já cadastrada nos Registros",
            value=True,
            key="s5_usar_fabrica_existente"
        )

    dados_fabrica_sugeridos = None

    if usar_fabrica_existente and not fabricas_existentes_s5.empty:
        opcoes_fabrica_s5 = []

        for _, linha_fab in fabricas_existentes_s5.iterrows():
            fab = clean(linha_fab.get("fabrica", ""))
            ce = clean(linha_fab.get("ce_bri", ""))
            opcoes_fabrica_s5.append(f"{fab} | {ce}")

        escolha_fabrica_s5 = st.selectbox(
            "Selecione uma fábrica já cadastrada",
            opcoes_fabrica_s5,
            key="s5_fabrica_existente_select"
        )

        fabrica_escolhida = escolha_fabrica_s5.split("|")[0].strip()
        ce_escolhido = escolha_fabrica_s5.split("|")[1].strip() if "|" in escolha_fabrica_s5 else ""

        dados_fabrica_sugeridos = buscar_dados_fabrica_existente(
            cliente_s5,
            fabrica_escolhida,
            ce_escolhido
        )

        fabrica_padrao = dados_fabrica_sugeridos.get("fabrica", fabrica_escolhida) if dados_fabrica_sugeridos else fabrica_escolhida
        ce_padrao = dados_fabrica_sugeridos.get("ce_bri", ce_escolhido) if dados_fabrica_sugeridos else ce_escolhido
        endereco_padrao = dados_fabrica_sugeridos.get("endereco_fabrica", "") if dados_fabrica_sugeridos else ""

        st.success("Dados da fábrica puxados dos Registros ✅")

    else:
        fabrica_padrao = ""
        ce_padrao = ""
        endereco_padrao = ""

    col_f1, col_f2 = st.columns(2)

    with col_f1:
        fabrica_s5 = st.text_input(
            "Fábrica",
            value=fabrica_padrao,
            placeholder="Ex: F01, F02, FÁBRICA 01...",
            key="s5_fabrica"
        )

        ce_bri_s5 = st.text_input(
            "CE-BRI da fábrica",
            value=ce_padrao,
            placeholder="Ex: CE-BRI-INNAC-02484-01A",
            key="s5_ce_bri"
        )

    with col_f2:
        endereco_s5 = st.text_area(
            "Endereço da fábrica",
            value="" if pd.isna(endereco_padrao) else str(endereco_padrao),
            placeholder="Cole aqui o endereço completo da fábrica",
            height=120,
            key="s5_endereco"
        )

    if clean(ce_bri_s5) and not clean(endereco_s5):
        dados_por_ce = buscar_dados_fabrica_existente(
            cliente_s5,
            "",
            ce_bri_s5
        )

        if dados_por_ce and clean(dados_por_ce.get("endereco_fabrica", "")):
            st.info("Existe endereço salvo para este CE-BRI nos Registros. Você pode copiar/preencher acima.")
            st.code(dados_por_ce.get("endereco_fabrica", ""))

    st.divider()
    st.subheader("Enviar Excel de processo")

    arquivo_s5 = st.file_uploader(
        "Envie o Excel com IP no nome",
        type=["xlsx", "xls"],
        key="s5_excel"
    )

    if arquivo_s5:
        ip_extraido = extrair_ip_processo(arquivo_s5.name)
        data_extraida = extrair_data_processo(arquivo_s5.name)
        tipo_detectado = detectar_tipo_processo(arquivo_s5.name)
        fabrica_detectada_nome = extrair_codigo_fabrica_nome(arquivo_s5.name)
        dados_fabrica_arquivo = buscar_fabrica_por_codigo_s5(cliente_s5, fabrica_detectada_nome) if fabrica_detectada_nome else None

        if not ip_extraido:
            st.error("Arquivo ignorado: o nome do arquivo precisa conter IP. Exemplo: INCLUSÃO 06-01-26 F01 IP-0094-26.xlsx")
        else:
            st.success(f"IP identificado: {ip_extraido}")
            st.info(f"Tipo detectado: {tipo_detectado} | Data detectada: {data_extraida or 'não encontrada'} | Fábrica detectada no arquivo: {fabrica_detectada_nome or 'não encontrada'}")

            if dados_fabrica_arquivo:
                st.success(
                    f"Fábrica vinculada automaticamente pela base {cliente_s5}: "
                    f"{dados_fabrica_arquivo.get('fabrica', '')} | {dados_fabrica_arquivo.get('ce_bri', '')}"
                )

                usar_dados_auto_s5 = st.checkbox(
                    "Usar CE-BRI e endereço encontrados automaticamente",
                    value=True,
                    key="s5_usar_dados_auto_arquivo"
                )

                if usar_dados_auto_s5:
                    fabrica_s5 = dados_fabrica_arquivo.get("fabrica", fabrica_s5)
                    ce_bri_s5 = dados_fabrica_arquivo.get("ce_bri", ce_bri_s5)
                    endereco_s5 = dados_fabrica_arquivo.get("endereco_fabrica", endereco_s5)
            elif fabrica_detectada_nome:
                st.warning(
                    f"O arquivo indica {fabrica_detectada_nome}, mas não encontrei essa fábrica nos Registros da base {cliente_s5}."
                )

            tipos = ["INCLUSAO", "MANUTENCAO", "RECERTIFICACAO", "INICIAL", "OUTROS"]

            tipo_s5 = st.selectbox(
                "Tipo de processo",
                tipos,
                index=tipos.index(tipo_detectado) if tipo_detectado in tipos else 0,
                key="s5_tipo"
            )

            data_s5 = st.text_input(
                "Data do processo",
                value=data_extraida or "",
                placeholder="AAAA-MM-DD",
                key="s5_data"
            )

            try:
                df_s5 = ler_excel_inclusao_sistema5(arquivo_s5)

                if df_s5.empty:
                    st.warning("Nenhum item encontrado nesse Excel. Verifique se há coluna de MODELO / referência.")
                else:
                    st.subheader("Prévia dos itens encontrados")
                    st.dataframe(df_s5, use_container_width=True)

                    if st.button("Salvar processo no Sistema 5", key="s5_salvar_processo"):
                        if not clean(cliente_s5) or not clean(fabrica_s5):
                            st.error("Informe cliente e fábrica antes de salvar.")
                        else:
                            total = salvar_inclusao_sistema5(
                                categoria_s5,
                                cliente_s5,
                                fabrica_s5,
                                ce_bri_s5,
                                endereco_s5,
                                tipo_s5,
                                ip_extraido,
                                data_s5,
                                arquivo_s5.name,
                                df_s5
                            )

                            st.success(f"{total} itens salvos no Sistema 5 ✅")

            except Exception as e:
                st.error(f"Erro ao ler Excel do Sistema 5: {e}")

    st.divider()
    st.subheader("Estrutura salva no Sistema 5")

    resumo_s5 = listar_sistema5_resumo()

    if resumo_s5.empty:
        st.info("Nenhum processo salvo ainda.")
    else:
        categorias = resumo_s5["categoria"].dropna().unique().tolist()

        for categoria in categorias:
            with st.expander(f"📁 {categoria}", expanded=False):
                bloco_categoria = resumo_s5[resumo_s5["categoria"] == categoria]
                clientes = bloco_categoria["cliente_base"].dropna().unique().tolist()

                for cliente in clientes:
                    st.markdown(f"### 📁 {cliente}")
                    bloco_cliente = bloco_categoria[bloco_categoria["cliente_base"] == cliente]
                    fabricas = bloco_cliente["fabrica"].dropna().unique().tolist()

                    for fabrica in fabricas:
                        with st.expander(f"🏭 {fabrica}", expanded=False):
                            bloco_fabrica = bloco_cliente[bloco_cliente["fabrica"] == fabrica]
                            st.dataframe(bloco_fabrica, use_container_width=True)

        st.download_button(
            "Baixar resumo Sistema 5 CSV",
            resumo_s5.to_csv(index=False, sep=";").encode("ISO-8859-1", errors="replace"),
            "sistema5_resumo.csv",
            "text/csv",
            key="download_sistema5_resumo"
        )

