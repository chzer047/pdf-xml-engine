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
    codigo TEXT,
    FOREIGN KEY(certificado_id) REFERENCES certificados(id)
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

for coluna in ["ce_bri", "rev", "data_atualizacao"]:
    try:
        cursor.execute(f"ALTER TABLE certificados ADD COLUMN {coluna} TEXT")
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


def extrair_rev(texto):
    texto = corrigir_texto(texto)

    padroes = [
        r"\bREV\.?\s*:?\s*(\d+)",
        r"\bREVISÃO\s*:?\s*(\d+)",
        r"\bREVISAO\s*:?\s*(\d+)"
    ]

    for padrao in padroes:
        match = re.search(padrao, texto, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))

    linhas = [clean(l) for l in texto.split("\n") if clean(l)]

    for i, linha in enumerate(linhas):
        if linha.upper() in ["REV", "REV."] and i + 1 < len(linhas):
            prox = re.sub(r"\D", "", linhas[i + 1])
            if prox:
                return int(prox)

    return 0


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

    rev = extrair_rev(texto)

    return {
        "ip_bri": ip_bri,
        "produto": produto,
        "ce_bri": ce_bri,
        "rev": rev,
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


def rows_para_dict(rows):
    dados = {}

    for r in rows:
        ordem, marca, modelo, nome, codigo = r
        chave = modelo if modelo else codigo

        dados[chave] = {
            "ordem": ordem,
            "marca": marca,
            "modelo": modelo,
            "nome": nome,
            "codigo": codigo
        }

    return dados


def registrar_historico(ip_bri, rev_antiga, rev_nova, modelo, codigo, tipo, campo, antigo, novo, arquivo):
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


def comparar_itens(ip_bri, rev_antiga, rev_nova, antigos_rows, novos_rows, arquivo):
    antigos = rows_para_dict(antigos_rows)
    novos = rows_para_dict(novos_rows)

    chaves_antigas = set(antigos.keys())
    chaves_novas = set(novos.keys())

    removidos = chaves_antigas - chaves_novas
    adicionados = chaves_novas - chaves_antigas
    comuns = chaves_antigas & chaves_novas

    total_logs = 0

    for chave in removidos:
        item = antigos[chave]
        registrar_historico(
            ip_bri,
            rev_antiga,
            rev_nova,
            item["modelo"],
            item["codigo"],
            "ITEM_REMOVIDO",
            "",
            f'{item["marca"]} | {item["modelo"]} | {item["nome"]} | {item["codigo"]}',
            "",
            arquivo
        )
        total_logs += 1

    for chave in adicionados:
        item = novos[chave]
        registrar_historico(
            ip_bri,
            rev_antiga,
            rev_nova,
            item["modelo"],
            item["codigo"],
            "ITEM_NOVO",
            "",
            "",
            f'{item["marca"]} | {item["modelo"]} | {item["nome"]} | {item["codigo"]}',
            arquivo
        )
        total_logs += 1

    campos = ["marca", "modelo", "nome", "codigo", "ordem"]

    for chave in comuns:
        antigo = antigos[chave]
        novo = novos[chave]

        for campo in campos:
            if str(antigo[campo]) != str(novo[campo]):
                registrar_historico(
                    ip_bri,
                    rev_antiga,
                    rev_nova,
                    novo["modelo"],
                    novo["codigo"],
                    "CAMPO_ALTERADO",
                    campo.upper(),
                    str(antigo[campo]),
                    str(novo[campo]),
                    arquivo
                )
                total_logs += 1

    conn.commit()
    return total_logs


def salvar_ou_atualizar_certificado(dados_certificado, rows, nome_arquivo):
    ip_bri = dados_certificado["ip_bri"]
    rev_nova = int(dados_certificado.get("rev") or 0)

    if not ip_bri:
        return "erro", "IP-BRI não encontrado. Não foi possível salvar no banco."

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

        registrar_historico(
            ip_bri,
            None,
            rev_nova,
            "",
            "",
            "CERTIFICADO_NOVO",
            "",
            "",
            f"Certificado cadastrado com {len(rows)} itens",
            nome_arquivo
        )

        conn.commit()
        return "salvo", f"Certificado novo salvo no banco. REV {rev_nova}."

    certificado_id, rev_antiga = existente
    rev_antiga = int(rev_antiga or 0)

    if rev_nova <= rev_antiga:
        registrar_historico(
            ip_bri,
            rev_antiga,
            rev_nova,
            "",
            "",
            "REV_IGNORADA",
            "",
            f"REV atual no banco: {rev_antiga}",
            f"REV enviada: {rev_nova}",
            nome_arquivo
        )
        conn.commit()

        return "ignorado", f"REV enviada ({rev_nova}) não é maior que a REV atual ({rev_antiga}). Banco não foi alterado."

    antigos_rows_db = cursor.execute("""
    SELECT ordem, marca, modelo, nome, codigo
    FROM itens
    WHERE certificado_id = ?
    """, (certificado_id,)).fetchall()

    antigos_rows = [
        [r[0], r[1], r[2], r[3], r[4]]
        for r in antigos_rows_db
    ]

    total_logs = comparar_itens(
        ip_bri,
        rev_antiga,
        rev_nova,
        antigos_rows,
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

    registrar_historico(
        ip_bri,
        rev_antiga,
        rev_nova,
        "",
        "",
        "CERTIFICADO_ATUALIZADO",
        "",
        f"REV antiga: {rev_antiga} | Itens antigos: {len(antigos_rows)}",
        f"REV nova: {rev_nova} | Itens novos: {len(rows)} | Alterações registradas: {total_logs}",
        nome_arquivo
    )

    conn.commit()

    return "atualizado", f"Certificado atualizado: REV {rev_antiga} → REV {rev_nova}. Alterações registradas: {total_logs}."


def exportar_todos_itens():
    return pd.read_sql_query("""
    SELECT
        i.marca AS marca,
        i.modelo AS modelo,
        i.nome AS nome,
        i.codigo AS codigo,
        c.ip_bri AS ip_bri,
        c.ce_bri AS ce_bri,
        c.rev AS rev,
        c.produto AS produto,
        c.data_emissao AS data_emissao,
        i.ordem AS ordem,
        c.arquivo_pdf AS arquivo_pdf,
        c.data_cadastro AS data_cadastro,
        c.data_atualizacao AS data_atualizacao
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

            dados_certificado = extrair_dados_certificado(pdf_path)

            df = pd.DataFrame(
                rows,
                columns=["ORDEM", "MARCA", "MODELO", "NOME", "CODIGO"]
            )

            st.success("Itens extraídos com sucesso ✅")
            st.dataframe(df, use_container_width=True)

            st.info(
                f"IP-BRI: {dados_certificado['ip_bri'] or 'Não encontrado'} | "
                f"CE-BRI: {dados_certificado['ce_bri'] or 'Não encontrado'} | "
                f"REV: {dados_certificado['rev']}"
            )

            duplicados = verificar_codigos_duplicados(df)

            if not duplicados.empty:
                st.warning("Foram encontrados códigos duplicados neste PDF.")
                st.dataframe(duplicados, use_container_width=True)

            status, mensagem = salvar_ou_atualizar_certificado(
                dados_certificado,
                rows,
                uploaded_file.name
            )

            if status in ["salvo", "atualizado"]:
                st.success(mensagem)
            elif status == "ignorado":
                st.warning(mensagem)
            else:
                st.error(mensagem)

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
        st.info("Ainda não há itens cadastrados.")
    else:
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

            col1, col2, col3, col4, col5 = st.columns(5)

            col1.metric("IP-BRI", dados_certificado["ip_bri"] or "Não encontrado")
            col2.metric("CE-BRI", dados_certificado["ce_bri"] or "Não encontrado")
            col3.metric("REV", dados_certificado["rev"])
            col4.metric("Produto", dados_certificado["produto"] or "Não encontrado")
            col5.metric("Data Emissão", dados_certificado["data_emissao"] or "Não encontrado")

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

                if st.button("Salvar / Atualizar banco"):
                    status, mensagem = salvar_ou_atualizar_certificado(
                        dados_certificado,
                        rows,
                        banco_file.name
                    )

                    if status in ["salvo", "atualizado"]:
                        st.success(mensagem)
                    elif status == "ignorado":
                        st.warning(mensagem)
                    else:
                        st.error(mensagem)

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
        campo = "i.modelo" if tipo_busca == "Referência / Modelo" else "i.codigo"

        resultado_item = pd.read_sql_query(f"""
        SELECT
            i.marca AS marca,
            i.modelo AS modelo,
            i.nome AS nome,
            i.codigo AS codigo,
            c.ip_bri AS ip_bri,
            c.ce_bri AS ce_bri,
            c.rev AS rev,
            c.produto AS produto,
            c.data_emissao AS data_emissao,
            i.ordem AS ordem
        FROM itens i
        INNER JOIN certificados c
        ON c.id = i.certificado_id
        WHERE {campo} LIKE ?
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

    st.subheader("Itens Repetidos")

    if st.button("Itens repetidos"):
        itens_repetidos = pd.read_sql_query("""
        SELECT
            i.marca AS marca,
            i.modelo AS modelo,
            i.nome AS nome,
            i.codigo AS codigo,
            c.ip_bri AS ip_bri,
            c.ce_bri AS ce_bri,
            c.rev AS rev,
            c.produto AS produto,
            c.data_emissao AS data_emissao,
            i.ordem AS ordem
        FROM itens i
        INNER JOIN certificados c
        ON c.id = i.certificado_id
        WHERE i.codigo IN (
            SELECT codigo
            FROM itens
            WHERE codigo IS NOT NULL
            AND codigo != ''
            GROUP BY codigo
            HAVING COUNT(*) > 1
        )
        ORDER BY i.codigo, i.marca, i.modelo, c.ip_bri
        """, conn)

        if itens_repetidos.empty:
            st.success("Nenhum código de barras repetido encontrado ✅")
        else:
            st.warning("Foram encontrados itens com código de barras repetido.")
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
            c.rev AS rev,
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

    st.divider()

    st.subheader("Histórico por IP-BRI")

    ip_historico = st.text_input("Digite o IP-BRI para consultar histórico")

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
            st.warning("Nenhum histórico encontrado para esse IP-BRI.")
        else:
            st.dataframe(historico, use_container_width=True)

            st.download_button(
                "Baixar histórico em CSV",
                historico.to_csv(index=False, sep=";").encode(
                    "ISO-8859-1",
                    errors="replace"
                ),
                "historico_ip_bri.csv",
                "text/csv"
            )
