import os
import time
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

app = FastAPI()

# Permisos CORS para comunicación abierta con Base44
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CONFIGURACIÓN DE SUPABASE
SUPABASE_URL = os.getenv("SUPABASE_URL", "tu_url_de_supabase")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "tu_api_key_de_supabase")
SUPABASE_TABLE = "inventario_sap"

COLUMNAS_SAP = ["Material", "Serial", "Texto", "Centro", "Almacen", "Movimiento", "Mov_texto", "Modelo", "Origen", "Precio", "Dias_Antiguedad", "Semaforo", "Fecha_Antiguedad", "Nro_Pedido"]
COLUMNAS_RELEVANTES = {"Material", "Serial", "Texto", "Centro", "Precio", "Dias_Antiguedad", "Semaforo", "Fecha_Antiguedad", "Nro_Pedido"}

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
    # MENSAJES DE DIAGNÓSTICO EN LOGS
    print(f"--> [CONSOLA] Iniciando bot para usuario: '{SinUs}'")
    
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
        time.sleep(12) 

        print("Paso 0: Desplegando formulario de login corporativo...")
        try:
            boton_desplegar = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="headerLoginButton"]/span | //*[@id="headerLoginButton"]'))
            )
            boton_desplegar.click()
            time.sleep(4)
        except:
            print("-> El botón superior no respondió o ya se auto-redireccionó.")

        if len(driver.find_elements(By.TAG_NAME, "iframe")) > 0:
            driver.switch_to.frame(0)

        print("Paso 1: Escribiendo credenciales e ingresando...")
        time.sleep(4)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, '//*[@id="j_username"]')))
        
        driver.execute_script(f"document.getElementById('j_username').value = '{SinUs}';")
        driver.execute_script(f"document.getElementById('j_password').value = '{SinPass}';")
        time.sleep(2) 
        
        boton_submit = driver.find_element(By.ID, "logOnFormSubmit")
        driver.execute_script("arguments.click();", boton_submit)
        print("-> Formulario enviado.")
        
        driver.switch_to.default_content()
        time.sleep(10)

        # ==========================================
        # PASO 2: ATAJO MAESTRO DIRECTO POR URL
        # ==========================================
        print("Paso 2: Saltando directamente al módulo objetivo mediante URL Maestra...")
        driver.get("https://flpnwc-d62f4ebf3.dispatcher.us2.hana.ondemand.com/sites/agentes#stock_antiguedad-Display")
        
        # Le damos una gran espera fija de 20 segundos para absorber la pesadez de Claro
        print("-> Esperando 20 segundos de cortesía extendida para la carga del módulo...")
        time.sleep(20)
        print("-> Pantalla cargada. Iniciando interacción con el reporte.")

        # ==========================================
        # CONFIGURACIÓN DE SELECTORES DE CONSULTA
        # ==========================================
        xpath_btn_consultar = '//*[@id="__xmlview8--button2-BDI-content"]'
        xpath_reabrir_filtros = '//*[@id="__xmlview4--panelSel-CollapsedImg-img"]'

        print("Paso 3: Consultando Stock Disponible Principal...")
        campo_inicio = WebDriverWait(driver, 25).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview8--input0"]')))
        campo_inicio.clear()
        campo_inicio.send_keys(rango_inicio)
        
        campo_fin = driver.find_element(By.XPATH, '//*[@id="__xmlview8--input1"]')
        campo_fin.clear()
        campo_fin.send_keys(rango_fin)
        
        driver.find_element(By.XPATH, xpath_btn_consultar).click()
        print("-> Consulta 1 enviada. Esperando tabla...")
        time.sleep(14) # Paciencia extendida para el renderizado del reporte
        registros_stock_actual.extend(extraer_datos_tabla(driver))

        print("Paso 4: Reabriendo filtros para Depósito de Reingreso...")
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, xpath_reabrir_filtros))).click()
        time.sleep(2)
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview11--rdb5-Button"]'))).click()
        driver.find_element(By.XPATH, xpath_btn_consultar).click()
        print("-> Consulta 2 enviada. Esperando tabla...")
        time.sleep(14)
        registros_stock_actual.extend(extraer_datos_tabla(driver))

        print("Paso 5: Reabriendo filtros para Stock en Tránsito...")
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, xpath_reabrir_filtros))).click()
        time.sleep(2)
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview4--rdb4"]/div/svg/circle'))).click()
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview4--rdb7-label"]'))).click()
        driver.find_element(By.XPATH, xpath_btn_consultar).click()
        print("-> Consulta 3 enviada. Esperando tabla...")
        time.sleep(14)
        registros_transito = extraer_datos_tabla(driver)

        print("Paso 6: Conectando a Supabase para actualizar datos...")
        limpiar_supabase_viejo()
        if registros_stock_actual:
            subir_a_supabase(registros_stock_actual, "Stock actual")
        if registros_transito:
            subir_a_supabase(registros_transito, "Stock en Tránsito")
        print("¡Sincronización masiva con Supabase completada con éxito total!")

    except Exception as e:
        import traceback
        print("¡Se detectó un fallo crítico en la navegación de SAP!")
        try:
            print(f"URL exacta donde se trabó el bot: {driver.current_url}")
            driver.save_screenshot("error_sap.png")
        except:
            pass
        traceback.print_exc()
    finally:
        driver.quit()

@app.get("/ver-error")
def ver_error():
    from fastapi.responses import FileResponse
    if os.path.exists("error_sap.png"):
        return FileResponse("error_sap.png")
    return {"status": "No hay capturas de error guardadas."}

@app.post("/ejecutar-bot")
def ejecutar_bot(payload: dict):
    r_inicio = str(payload.get("rango_inicio", ""))
    r_fin = str(payload.get("rango_fin", ""))
    usuario = str(payload.get("SinUs", payload.get("sinus", payload.get("Sinus", payload.get("usuario_sap", ""))))).strip()
    password = str(payload.get("SinPass", payload.get("sinpass", payload.get("Sinpass", payload.get("password_sap", ""))))).strip()
    
    tarea_bot_sap(r_inicio, r_fin, usuario, password)
    return {"status": "Proceso ejecutado"}
