# Usamos la imagen oficial de Selenium con Chrome preinstalado
FROM selenium/standalone-chrome:latest

# Cambiamos temporalmente a usuario administrador (root) para instalar Python
USER root

# Actualizar el sistema e instalar Python 3 junto con pip
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiamos tus archivos del repositorio al contenedor
COPY . .

# Forzamos la instalación de las librerías omitiendo restricciones del sistema
RUN python3 -m pip install --no-cache-dir --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt --break-system-packages

# Exponer el puerto estándar requerido por Render
EXPOSE 8080

# Comando para encender el servidor de tu API con FastAPI
CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
