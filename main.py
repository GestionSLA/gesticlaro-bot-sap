import os
import time
import requests
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

app = FastAPI()

# La URL del Webhook se mantiene fija para saber a dónde devolver los datos
URL_WEBHOOK_BASE44 = os.getenv("URL_WEBHOOK_BASE44", "https://base44.com")

COLUMNAS_SAP = ["Material", "Serial", "Texto", "Centro", "Almacen", "Movimiento", "Mov_texto", "Modelo", "Origen", "Precio", "Dias_Antiguedad", "Semaforo", "Fecha_Antiguedad", "Nro_Pedido"]
COLUMNAS_RELEVANTES = {"Material", "Serial", "Texto", "Centro", "Precio", "Dias_Antiguedad", "Semaforo", "Fecha_Antiguedad", "Nro_Pedido"}

# ==========================================
# MODIFICACIÓN 1: El molde del paquete JSON
# ==========================================
class ConsultaRequest(BaseModel):
    rango_inicio: str
    rango_fin: str
    usuario_sap: str    # <-- Ahora Base44 debe enviar esto
    password_sap: str   # <-- Ahora Base44 debe enviar esto

def extraer_datos_tabla(driver):
    xpath_tabla = "//table[contains(@class, 'sapUiTableCtrl')]//tbody | //table[contains(@class, 'sapMListTbl')]//tbody"
    try:
        tabla_body = WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.XPATH, xpath_tabla)))
        filas = tabla_body.find_elements(By.TAG_NAME, "tr")
        resultados = []
        for fila in filas:
            celdas = fila.find_elements(By.TAG_NAME, "td")
            if celdas:
                valores = [celda.text.strip() for celda in celdas]
                if len(valores) >= len(COLUMNAS_SAP):
                    registro = {COLUMNAS_SAP[i]: valores[i] for i in range(len(COLUMNAS_SAP)) if COLUMNAS_SAP[i] in COLUMNAS_RELEVANTES}
                    resultados.append(registro)
        return resultados
    except:
        return []

# ==========================================
# MODIFICACIÓN 2: Uso de datos dinámicos
# ==========================================
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
        driver.get("https://ondemand.com")

        # Login usando las variables que viajan desde Base44
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="headerLoginButton"]/span'))).click()
        campo_usuario = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="j_username"]')))
        
        campo_usuario.send_keys(usuario_sap)  # <-- Cambiado
        driver.find_element(By.XPATH, '//*[@id="j_password"]').send_keys(password_sap)  # <-- Cambiado
        
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

        # Envío de vuelta a Base44
        payload = {
            "metadata": {"rango": f"{rango_inicio}-{rango_fin}"},
            "stock_actual": registros_stock_actual,
            "stock_en_transito": registros_transito
        }
        requests.post(URL_WEBHOOK_BASE44, json=payload, timeout=40)

    except Exception as e:
        print(f"Error en segundo plano: {e}")
    finally:
        driver.quit()

# ==========================================
# MODIFICACIÓN 3: Pasar parámetros a la tarea
# ==========================================
@app.post("/ejecutar-bot")
def ejecutar_bot(datos: ConsultaRequest, background_tasks: BackgroundTasks):
    # Despacha las credenciales y rangos hacia el bot en segundo plano
    background_tasks.add_task(tarea_bot_sap, datos.rango_inicio, datos.rango_fin, datos.usuario_sap, datos.password_sap)
    return {"status": "Proceso de actualización iniciado en la nube"}
