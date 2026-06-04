import os
import time
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

app = FastAPI()

# Permisos CORS para comunicación con Base44
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CONFIGURACIÓN DE SUPABASE (Se carga desde el entorno de Render)
SUPABASE_URL = os.getenv("SUPABASE_URL", "tu_url_de_supabase")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "tu_api_key_de_supabase")
SUPABASE_TABLE = "inventario_sap"

COLUMNAS_SAP = ["Material", "Serial", "Texto", "Centro", "Almacen", "Movimiento", "Mov_texto", "Modelo", "Origen", "Precio", "Dias_Antiguedad", "Semaforo", "Fecha_Antiguedad", "Nro_Pedido"]
COLUMNAS_RELEVANTES = {"Material", "Serial", "Texto", "Centro", "Precio", "Dias_Antiguedad", "Semaforo", "Fecha_Antiguedad", "Nro_Pedido"}

# Sincronizado con los nombres de variables que usas en Base44
class ConsultaRequest(BaseModel):
    rango_inicio: str
    rango_fin: str
    SinUs: str       # <-- Actualizado según tu sistema
    SinPass: str     # <-- Actualizado según tu sistema

def limpiar_supabase_viejo():
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
    headers = {"Authorization": f"Bearer {SUPABASE_KEY}", "apikey": SUPABASE_KEY}
    requests.delete(url, headers=headers, params={"id": "neq.0"})

def subir_a_supabase(registros, categoria):
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "apikey": SUPABASE_KEY,
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
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
            celdas = fila.find_elements(By.TAG_NAME, "td")
            if celdas:
                valores = [celda.text.strip() for celda in celdas]
                if len(valores) >= len(COLUMNAS_SAP):
                    registro = {COLUMNAS_SAP[i]: valores[i] for i in range(len(COLUMNAS_SAP)) if COLUMNAS_SAP[i] in COLUMNAS_RELEVANTES}
                    resultados.append(registro)
        return resultados
    except:
        return []

def tarea_bot_sap(rango_inicio: str, rango_fin: str, SinUs: str, SinPass: str):
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    driver = webdriver.Chrome(options=chrome_options)
    registros_stock_actual = []
    registros_transito = []

    try:
        print("Iniciando simulación del navegador... Abriendo SAP Fiori Claro")
        driver.get("https://flpnwc-d62f4ebf3.dispatcher.us2.hana.ondemand.com/sites/agentes#home-Display")
        time.sleep(5)

        print("Paso 0: Verificando presencia del botón superior...")
        try:
            # Forzamos la búsqueda usando Javascript y Xpath para ver si está el botón
            boton_superior = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="headerLoginButton"]/span'))
            )
            driver.execute_script("arguments[0].click();", boton_superior)
            print("-> Botón superior presionado mediante JS con éxito.")
            time.sleep(4)
        except:
            print("-> El botón superior no respondió o ya estamos en el login. Continuando...")

        print("Paso 1: Escribiendo credenciales e ingresando...")
        # Espera estricta a que el formulario esté listo en pantalla
        campo_usuario = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="j_username"]'))
        )
        
        # Inyección directa por JavaScript para evitar bloqueos de foco o idioma
        driver.execute_script("document.getElementById('j_username').value = arguments[0];", SinUs)
        driver.execute_script("document.getElementById('j_password').value = arguments[0];", SinPass)
        time.sleep(1)

        print("-> Presionando botón de ingreso 'Log On'...")
        boton_submit = driver.find_element(By.ID, "logOnFormSubmit")
        driver.execute_script("arguments[0].click();", boton_submit)
        print("-> Formulario enviado.")
        time.sleep(8)

        print("Paso 2: Navegando por el menú de aplicaciones...")
        boton_apps = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//*[contains(@id, 'btnApplicaciones')]"))
        )
        driver.execute_script("arguments[0].click();", boton_apps)
        time.sleep(3)

        tile_modulo = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="__tile3-focus"]'))
        )
        driver.execute_script("arguments[0].click();", tile_modulo)
        time.sleep(5)

        xpath_btn_consultar = '//*[@id="__xmlview8--button2-BDI-content"]'
        xpath_reabrir_filtros = '//*[@id="__xmlview4--panelSel-CollapsedImg-img"]'

        print("Paso 3: Consultando Stock Disponible Principal...")
        campo_inicio = WebDriverWait(driver, 25).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview8--input0"]')))
        campo_inicio.clear()
        campo_inicio.send_keys(rango_inicio)
        driver.find_element(By.XPATH, '//*[@id="__xmlview8--input1"]').clear()
        driver.find_element(By.XPATH, '//*[@id="__xmlview8--input1"]').send_keys(rango_fin)
        driver.find_element(By.XPATH, xpath_btn_consultar).click()
        time.sleep(12)
        registros_stock_actual.extend(extraer_datos_tabla(driver))

        print("Paso 4: Reabriendo filtros para Depósito de Reingreso...")
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, xpath_reabrir_filtros))).click()
        time.sleep(1)
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview11--rdb5-Button"]'))).click()
        driver.find_element(By.XPATH, xpath_btn_consultar).click()
        time.sleep(12)
        registros_stock_actual.extend(extraer_datos_tabla(driver))

        print("Paso 5: Reabriendo filtros para Stock en Tránsito...")
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, xpath_reabrir_filtros))).click()
        time.sleep(1)
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview4--rdb4"]/div/svg/circle'))).click()
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview4--rdb7-label"]'))).click()
        driver.find_element(By.XPATH, xpath_btn_consultar).click()
        time.sleep(12)
        registros_transito = extraer_datos_tabla(driver)

        print("Paso 6: Conectando a Supabase para actualizar datos...")
        limpiar_supabase_viejo()
        if registros_stock_actual:
            subir_a_supabase(registros_stock_actual, "Stock actual")
        if registros_transito:
            subir_a_supabase(registros_transito, "Stock en Tránsito")
        print("Sincronización completada de forma exitosa.")

    except Exception as e:
        import traceback
        print("¡Se detectó un fallo crítico en la navegación de SAP!")
        try:
            print(f"URL exacta donde se trabó el bot: {driver.current_url}")
            driver.save_screenshot("error_sap.png")
            print("Captura de pantalla guardada como 'error_sap.png'.")
        except:
            pass
        traceback.print_exc()
    finally:
        driver.quit()

@app.get("/ver-error")
def ver_error():
    if os.path.exists("error_sap.png"):
        return FileResponse("error_sap.png")
    return {"status": "No hay capturas de error guardadas por el momento."}

@app.post("/ejecutar-bot")
def ejecutar_bot(datos: ConsultaRequest):
    tarea_bot_sap(datos.rango_inicio, datos.rango_fin, datos.SinUs, datos.SinPass)
    return {"status": "Proceso ejecutado"}
