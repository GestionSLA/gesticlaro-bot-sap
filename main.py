import os
import time
import requests
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware  # <-- NUEVA LÍNEA
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

app = FastAPI()

# NUEVO BLOQUE: Habilitar permisos CORS universales para que Base44 hable con Render
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CONFIGURACIÓN DE SUPABASE (Se mantiene igual abajo...)
SUPABASE_URL = os.getenv("SUPABASE_URL", "tu_url_de_supabase")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "tu_api_key_de_supabase")
SUPABASE_TABLE = "inventario_sap"

COLUMNAS_SAP = ["Material", "Serial", "Texto", "Centro", "Almacen", "Movimiento", "Mov_texto", "Modelo", "Origen", "Precio", "Dias_Antiguedad", "Semaforo", "Fecha_Antiguedad", "Nro_Pedido"]
COLUMNAS_RELEVANTES = {"Material", "Serial", "Texto", "Centro", "Precio", "Dias_Antiguedad", "Semaforo", "Fecha_Antiguedad", "Nro_Pedido"}

class ConsultaRequest(BaseModel):
    rango_inicio: str
    rango_fin: str
    usuario_sap: str
    password_sap: str

def limpiar_supabase_viejo():
    """Borra todos los registros actuales de la tabla en Supabase"""
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "apikey": SUPABASE_KEY
    }
    requests.delete(url, headers=headers, params={"id": "neq.0"})

def subir_a_supabase(registros, categoria):
    """Sube los registros estructurados directamente a Supabase"""
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "apikey": SUPABASE_KEY,
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    
    # Aseguramos el nombre exacto de la columna en Supabase (toda en minúsculas)
    for reg in registros:
        reg["Categoria"] = categoria
        
    requests.post(url, headers=headers, json=registros)

def extraer_datos_tabla(driver):
    xpath_tabla = "//table[contains(@class, 'sapUiTableCtrl')]//tbody | //table[contains(@class, 'sapMListTbl')]//tbody"
    try:
        tabla_body = WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.XPATH, xpath_tabla)))
        filas = tabla_body.find_elements(By.TAG_NAME, "tr")
        resultados = []
        for fila in filas:
            celdas = fila.find_elements(By.TAG_NAME, "tr" if "sapUiTableCtrl" in xpath_tabla else "td")
            # Si SAP usa celdas estándar td o divs internos, extraemos su texto
            celdas_datos = fila.find_elements(By.TAG_NAME, "td") if not celdas else celdas
            if celdas_datos:
                valores = [celda.text.strip() for celda in celdas_datos]
                if len(valores) >= len(COLUMNAS_SAP):
                    registro = {COLUMNAS_SAP[i]: valores[i] for i in range(len(COLUMNAS_SAP)) if COLUMNAS_SAP[i] in COLUMNAS_RELEVANTES}
                    resultados.append(registro)
        return resultados
    except:
        return []

def tarea_bot_sap(rango_inicio: str, rango_fin: str, usuario_sap: str, password_sap: str):
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    driver = webdriver.Chrome(options=chrome_options)
    registros_stock_actual = []
    registros_transito = []

    try:
        # URL REAL Y COMPLETA CORREGIDA DE SAP CLARO AGENTES
        driver.get("https://flpnwc-d62f4ebf3.dispatcher.us2.hana.ondemand.com/sites/agentes#home-Display")

        # Login
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="headerLoginButton"]/span'))).click()
        campo_usuario = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="j_username"]')))
        campo_usuario.send_keys(usuario_sap)
        driver.find_element(By.XPATH, '//*[@id="j_password"]').send_keys(password_sap)
        driver.find_element(By.ID, "logOnFormSubmit").click()

        # Navegación
        WebDriverWait(driver, 25).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="btnApplicaciones-BDI-content"]'))).click()
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__tile3-focus"]'))).click()

        xpath_btn_consultar = '//*[@id="__xmlview8--button2-BDI-content"]'
        xpath_reabrir_filtros = '//*[@id="__xmlview4--panelSel-CollapsedImg-img"]'

        # --- PASO 1: Stock Disponible ---
        campo_inicio = WebDriverWait(driver, 25).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview8--input0"]')))
        campo_inicio.clear()
        campo_inicio.send_keys(rango_inicio)
        driver.find_element(By.XPATH, '//*[@id="__xmlview8--input1"]').clear()
        driver.find_element(By.XPATH, '//*[@id="__xmlview8--input1"]').send_keys(rango_fin)
        driver.find_element(By.XPATH, xpath_btn_consultar).click()
        time.sleep(12)
        registros_stock_actual.extend(extraer_datos_tabla(driver))

        # --- PASO 2: Depósito de Reingreso ---
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, xpath_reabrir_filtros))).click()
        time.sleep(1)
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview11--rdb5-Button"]'))).click()
        driver.find_element(By.XPATH, xpath_btn_consultar).click()
        time.sleep(12)
        registros_stock_actual.extend(extraer_datos_tabla(driver))

        # --- PASO 3: Stock en Tránsito ---
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, xpath_reabrir_filtros))).click()
        time.sleep(1)
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview4--rdb4"]/div/svg/circle'))).click()
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview4--rdb7-label"]'))).click()
        driver.find_element(By.XPATH, xpath_btn_consultar).click()
        time.sleep(12)
        registros_transito = extraer_datos_tabla(driver)

        # --- ENVÍO DE DATOS A SUPABASE ---
        print("Limpiando registros antiguos de Supabase...")
        limpiar_supabase_viejo()
        
        print("Subiendo nuevo Stock Actual...")
        if registros_stock_actual:
            subir_a_supabase(registros_stock_actual, "Stock actual")
            
        print("Subiendo nuevo Stock en Tránsito...")
        if registros_transito:
            subir_a_supabase(registros_transito, "Stock en Tránsito")
        print("¡Sincronización con Supabase completada con éxito!")

        except Exception as e:
        import traceback
        print("¡Se detectó un fallo en la navegación de SAP!")
        traceback.print_exc()
    finally:
        driver.quit()

@app.post("/ejecutar-bot")
def ejecutar_bot(datos: ConsultaRequest):
    try:
        tarea_bot_sap(datos.rango_inicio, datos.rango_fin, datos.usuario_sap, datos.password_sap)
        return {"status": "Sincronización completada"}
    except Exception as e:
        return {"status": "Error en la ejecución", "error": str(e)}
