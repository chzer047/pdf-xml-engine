FROM python:3.11-slim

WORKDIR /app

# Instalar dependências do sistema necessárias para pymupdf e pdfplumber
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o app
COPY . .

# Criar pasta .streamlit e config
RUN mkdir -p .streamlit

# Expor porta
EXPOSE 8501

# Comando de inicialização
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
