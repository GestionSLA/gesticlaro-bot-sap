import os
import json
import time
import traceback
from datetime import datetime, timezone
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.remote.remote_connection import RemoteConnection

# El cliente HTTP de Selenium (Python -> chromedriver) tiene un timeout fijo
# de 120s por defecto, INDEPENDIENTE del page_load_timeout de Chrome. Si
# driver.get() tarda más que esto, urllib3 lanza ReadTimeoutError antes de
# que nuestro page_load_timeout pueda actuar. Lo subimos a 300s.
RemoteConnection.set_timeout(300)

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────
# Las credenciales se leen de variables de entorno (configuradas como
# GitHub Secrets: SAP_USER y SAP_PASS). Si no existen, usa estos valores
# por defecto (recomendado: moverlos a Secrets y borrar de aquí).
USUARIO = os.getenv("SAP_USER", "AGED049128")
PASSWORD = os.getenv("SAP_PASS", "Lunes18/")

RANGO_INICIO = os.getenv("SAP_RANGO_INICIO", "")
RANGO_FIN = os.getenv("SAP_RANGO_FIN", "")

URL_HOME = "https://flpnwc-d62f4ebf3.dispatcher.us2.hana.ondemand.com/sites/agentes#home-Display"
URL_STOCK = "https://flpnwc-d62f4ebf3.dispatcher.us2.hana.ondemand.com/sites/agentes#stock_antiguedad-Display"

SALIDA_JSON = os.path.join("data", "stock_sap.json")
SALIDA_LOG = os.path.join("data", "ultimo_log.txt")

COLUMNAS_SAP = [
    "Material", "Serial", "Texto", "Centro", "Almacen", "Movimiento",
    "Mov_texto", "Modelo", "Origen", "Precio", "Dias_Antiguedad",
    "Semaforo", "Fecha_Antiguedad", "Nro_Pedido"
]
COLUMNAS_RELEVANTES = {
    "Material", "Serial", "Texto", "Centro", "Precio",
    "Dias_Antiguedad", "Semaforo", "Fecha_Antiguedad", "Nro_Pedido"
}

LOG_LINES = []


def log(msg):
    print(msg)
    LOG_LINES.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def guardar_log():
    os.makedirs("data", exist_ok=True)
    with open(SALIDA_LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(LOG_LINES))


def extraer_datos_tabla(driver):
    xpath_tabla = (
        "//table[contains(@class, 'sapUiTableCtrl')]//tbody | "
        "//table[contains(@class, 'sapMListTbl')]//tbody"
    )
    try:
        tabla_body = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, xpath_tabla))
        )
        filas = tabla_body.find_elements(By.TAG_NAME, "tr")
        resultados = []
        for fila in filas:
            celdas = fila.find_elements(By.TAG_NAME, "td")
            if celdas:
                valores = [c.text.strip() for c in celdas]
                if len(valores) >= len(COLUMNAS_SAP):
                    registro = {
                        COLUMNAS_SAP[i]: valores[i]
                        for i in range(len(COLUMNAS_SAP))
                        if COLUMNAS_SAP[i] in COLUMNAS_RELEVANTES
                    }
                    resultados.append(registro)
        return resultados
    except Exception as e:
        log(f"Aviso: no se pudo leer la tabla ({e})")
        return []


def guardar_resultado(data, status, mensaje):
    os.makedirs("data", exist_ok=True)
    salida = {
        "status": status,
        "mensaje": mensaje,
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "cantidad": len(data),
        "data": data,
    }
    with open(SALIDA_JSON, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)
    log(f"Guardado {SALIDA_JSON} ({len(data)} registros, status={status})")


def cargar_pagina(driver, url, timeout=180, reintentos=2):
    """
    Navega a una URL con timeout extendido. Si la página tarda demasiado
    en disparar el evento 'load' (común en SPAs pesadas de SAP), detiene
    la carga con window.stop() y continúa: el DOM suele estar usable
    igual aunque la página "siga cargando" recursos secundarios.
    """
    driver.set_page_load_timeout(timeout)
    for intento in range(1, reintentos + 1):
        try:
            log(f"Cargando {url} (intento {intento}/{reintentos}, timeout={timeout}s)...")
            driver.get(url)
            return True
        except (TimeoutException, Exception) as e:
            log(f"Error/timeout cargando la página (intento {intento}): {type(e).__name__}: {e}")
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
            # Verificar si al menos algo se cargó
            try:
                body_len = len(driver.execute_script("return document.body ? document.body.innerHTML.length : 0;"))
            except Exception:
                body_len = 0
            log(f"Contenido cargado tras detener: {body_len} caracteres en <body>")
            if body_len and body_len > 500:
                return True
            if intento == reintentos:
                log("Se alcanzó el máximo de reintentos. Se continúa con lo que haya cargado.")
                return False
            time.sleep(5)
    return False


def main():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(options=chrome_options)
    registros_stock_actual = []
    registros_transito = []

    try:
        log("Abriendo portal SAP Fiori de Claro...")
        cargar_pagina(driver, URL_HOME, timeout=180, reintentos=2)
        time.sleep(12)

        log("Paso 0: Verificando si requiere desplegar login corporativo...")
        try:
            boton_desplegar = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable(
                    (By.XPATH, '//*[@id="headerLoginButton"]/span | //*[@id="headerLoginButton"]')
                )
            )
            boton_desplegar.click()
            log("Botón superior encontrado y presionado.")
            time.sleep(4)
        except Exception:
            log("El botón superior no respondió. Buscando formulario directamente...")

        os.makedirs("data", exist_ok=True)
        driver.save_screenshot("data/pre_fill.png")

        log("Paso 1: Escribiendo credenciales e ingresando...")
        time.sleep(4)

        # Diagnóstico: buscar j_username tanto en el documento principal
        # como dentro de cada iframe, e inyectar en TODOS los contextos
        # donde exista (puede haber más de un formulario en la página).
        driver.switch_to.default_content()
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        log(f"Iframes detectados en el documento principal: {len(iframes)}")
        for i, fr in enumerate(iframes):
            try:
                log(f"  iframe[{i}] src={fr.get_attribute('src')}")
            except Exception as e:
                log(f"  iframe[{i}] error leyendo src: {e}")

        inyectado_en_algun_lado = False

        # 1) Documento principal
        driver.switch_to.default_content()
        campos_main = driver.find_elements(By.XPATH, '//*[@id="j_username"]')
        log(f"j_username en documento principal: {len(campos_main)} elemento(s)")
        if campos_main:
            driver.execute_script("document.getElementById('j_username').value = arguments[0];", USUARIO)
            driver.execute_script("document.getElementById('j_password').value = arguments[0];", PASSWORD)
            val = driver.execute_script("return document.getElementById('j_username').value;")
            log(f"  -> Valor tras inyección en doc. principal: '{val}'")
            if val:
                inyectado_en_algun_lado = True

        # 2) Cada iframe de primer nivel
        frame_inyectado = None
        for i in range(len(iframes)):
            driver.switch_to.default_content()
            try:
                frames = driver.find_elements(By.TAG_NAME, "iframe")
                driver.switch_to.frame(frames[i])
            except Exception as e:
                log(f"  No se pudo entrar al iframe[{i}]: {e}")
                continue

            campos_iframe = driver.find_elements(By.XPATH, '//*[@id="j_username"]')
            log(f"j_username dentro de iframe[{i}]: {len(campos_iframe)} elemento(s)")
            if campos_iframe:
                driver.execute_script("document.getElementById('j_username').value = arguments[0];", USUARIO)
                driver.execute_script("document.getElementById('j_password').value = arguments[0];", PASSWORD)
                val = driver.execute_script("return document.getElementById('j_username').value;")
                log(f"  -> Valor tras inyección en iframe[{i}]: '{val}'")
                if val:
                    inyectado_en_algun_lado = True
                    frame_inyectado = i

        time.sleep(3)
        driver.save_screenshot("data/filled.png")

        if not inyectado_en_algun_lado:
            log("ADVERTENCIA: no se pudo confirmar la inyección en ningún contexto. Se continúa para diagnosticar.")

        # Si se inyectó dentro de un iframe, posicionarse ahí para el submit.
        # Si fue en el documento principal (o no se confirmó en ningún lado),
        # nos quedamos / volvemos al documento principal.
        driver.switch_to.default_content()
        if frame_inyectado is not None:
            frames = driver.find_elements(By.TAG_NAME, "iframe")
            driver.switch_to.frame(frames[frame_inyectado])

        log("Presionando botón de ingreso 'Log On'...")
        time.sleep(2)

        try:
            boton_submit = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "logOnFormSubmit"))
            )
            driver.execute_script("arguments[0].click();", boton_submit)
        except Exception:
            try:
                boton_texto = WebDriverWait(driver, 8).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//button[contains(text(), 'Log On')] | //input[@value='Log On']")
                    )
                )
                driver.execute_script("arguments[0].click();", boton_texto)
            except Exception:
                boton_clase = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CLASS_NAME, "comSapIdpIdpButtons"))
                )
                driver.execute_script("arguments[0].click();", boton_clase)

        log("Procesando login...")
        driver.switch_to.default_content()
        time.sleep(12)

        driver.save_screenshot("data/post_login.png")

        log("Navegando directo al módulo de stock por antigüedad (URL directa)...")
        cargar_pagina(driver, URL_STOCK, timeout=180, reintentos=2)
        time.sleep(22)
        driver.save_screenshot("data/post_stock_nav.png")

        xpath_btn_consultar = '//*[@id="__xmlview4--button2-BDI-content"]'
        xpath_reabrir_filtros = '//*[@id="__xmlview4--panelSel-CollapsedImg-img"]'

        log("Consultando Stock Disponible Principal...")
        campo_inicio = WebDriverWait(driver, 25).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview4--input0-inner"]'))
        )
        campo_inicio.clear()
        campo_inicio.send_keys(RANGO_INICIO)
        campo_fin = driver.find_element(By.XPATH, '//*[@id="__xmlview4--input1-inner"]')
        campo_fin.clear()
        campo_fin.send_keys(RANGO_FIN)
        driver.find_element(By.XPATH, xpath_btn_consultar).click()
        time.sleep(12)
        registros_stock_actual.extend(extraer_datos_tabla(driver))
        log(f"Stock principal: {len(registros_stock_actual)} registros")

        log("Consultando Depósito de Reingreso...")
        WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, xpath_reabrir_filtros))
        ).click()
        time.sleep(1)
        WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview4--rdb5-label-bdi"]'))
        ).click()
        driver.find_element(By.XPATH, xpath_btn_consultar).click()
        time.sleep(12)
        registros_stock_actual.extend(extraer_datos_tabla(driver))
        log(f"Stock total acumulado: {len(registros_stock_actual)} registros")

        log("Consultando Stock en Tránsito...")
        WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, xpath_reabrir_filtros))
        ).click()
        time.sleep(1)
        WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview4--rdb4-label-bdi"]'))
        ).click()
        WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="__xmlview4--rdb7-label-bdi"]'))
        ).click()
        driver.find_element(By.XPATH, xpath_btn_consultar).click()
        time.sleep(12)
        registros_transito = extraer_datos_tabla(driver)
        log(f"Stock en tránsito: {len(registros_transito)} registros")

        resultado_total = []
        for r in registros_stock_actual:
            r2 = dict(r)
            r2["Categoria"] = "Stock actual"
            resultado_total.append(r2)
        for r in registros_transito:
            r2 = dict(r)
            r2["Categoria"] = "Stock en Tránsito"
            resultado_total.append(r2)

        guardar_resultado(resultado_total, "listo", f"Sincronización completada: {len(resultado_total)} registros")

    except Exception as e:
        traceback.print_exc()
        log(f"ERROR CRÍTICO: {e}")
        try:
            os.makedirs("data", exist_ok=True)
            driver.save_screenshot("data/error_sap.png")
            log(f"URL al momento del error: {driver.current_url}")
        except Exception:
            pass
        guardar_resultado([], "error", str(e))
    finally:
        guardar_log()
        driver.quit()


if __name__ == "__main__":
    main()
