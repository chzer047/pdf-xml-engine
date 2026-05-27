# ==========================================
# TABS
# ==========================================

aba1, aba2, aba3 = st.tabs([
    "PDF → XML",
    "Banco de Certificados",
    "Consultar IP-BRI"
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

            duplicados = verificar_codigos_duplicados(df)

            if not duplicados.empty:
                st.warning("Códigos duplicados encontrados.")
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
# ABA BANCO
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
        key="pesquisa_item"
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
        ORDER BY i.marca, i.modelo, c.ip_bri
        """, conn, params=(f"%{termo_busca}%",))

        if resultado_item.empty:
            st.warning("Nenhum item encontrado.")
        else:
            st.success("Item encontrado ✅")
            st.dataframe(resultado_item, use_container_width=True)

    st.divider()

    st.subheader("Itens Repetidos")

    if st.button("Itens repetidos", key="btn_repetidos"):

        itens_repetidos = pd.read_sql_query("""
        SELECT
            i.marca,
            i.modelo,
            i.nome,
            i.codigo,
            c.ip_bri,
            c.ce_bri,
            c.rev
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
            c.rev
        FROM itens i
        INNER JOIN certificados c
        ON c.id = i.certificado_id
        WHERE i.marca = ?
        ORDER BY i.modelo
        """, conn, params=(marca_filtro,))

        st.dataframe(resultado_marca, use_container_width=True)

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
# ABA CONSULTAR IP-BRI
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

            st.warning("Nenhum item encontrado para esse IP-BRI.")

        else:

            st.success(f"{len(itens_ip)} itens encontrados ✅")

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
                f"itens_ip_bri.csv",
                "text/csv"
            )
