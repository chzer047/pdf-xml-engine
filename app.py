def extrair_fabricante_primeira_pagina(pdf_path):

    doc = fitz.open(str(pdf_path))

    if len(doc) == 0:
        return None

    texto = doc[0].get_text()
    texto = corrigir_texto(texto)

    linhas = [
        clean(linha)
        for linha in texto.split("\n")
        if clean(linha)
    ]

    fabricante_linhas = []
    capturando = False

    parar_em = [
        "IMPORTADOR",
        "CNPJ",
        "PRODUTO",
        "MARCA",
        "MODELO",
        "NORMA",
        "DATA",
        "PÁGINA",
        "PAGINA",
        "CERTIFICADO",
        "NÚMERO",
        "NUMERO",
        "ETAPA",
        "IP-BRI"
    ]

    for linha in linhas:

        linha_upper = linha.upper()

        # INICIA CAPTURA
        if "FABRICANTE:" in linha_upper:

            capturando = True

            conteudo = linha.split(":", 1)[1].strip()

            if conteudo:
                fabricante_linhas.append(conteudo)

            continue

        # CONTINUA CAPTURANDO
        if capturando:

            # PARA SE ENCONTRAR OUTRO CAMPO
            if any(
                linha_upper.startswith(p)
                for p in parar_em
            ):
                break

            fabricante_linhas.append(linha)

    fabricante = clean(
        " ".join(fabricante_linhas)
    )

    # REMOVE ESPAÇOS DUPLOS
    fabricante = re.sub(
        r"\s+",
        " ",
        fabricante
    ).strip()

    return fabricante or None
