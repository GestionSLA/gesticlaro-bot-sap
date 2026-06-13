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
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

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


def set_value_js(driver, element_id, valor):
    driver.execute_script(
        """
        const el = document.getElementById(arguments[0]);
        if (!el) return false;
        el.focus();
        el.value = arguments[1];
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('keyup', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
        return true;
        """,
        element_id, valor
    )


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


def escribir_lento(elemento, texto, delay=0.08):
    """Escribe carácter por carácter con pequeñas pausas. Algunos formularios
    SAP UI5/IAS no registran el valor si se escribe todo de una vez."""
    for ch in texto:
        elemento.send_keys(ch)
        time.sleep(delay)


def encontrar_campo(driver, by, selector, timeout=15):
    """
    Busca un elemento recorriendo el documento principal y todos los iframes
    (1 nivel de profundidad). Devuelve el elemento ya posicionado en el frame
    correcto, o None si no lo encuentra en ningún lado.
    """
    driver.switch_to.default_content()
    try:
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, selector))
        )
    except Exception:
        pass

    driver.switch_to.default_content()
    total_iframes = len(driver.find_elements(By.TAG_NAME, "iframe"))
    for idx in range(total_iframes):
        driver.switch_to.default_content()
        try:
            frames = driver.find_elements(By.TAG_NAME, "iframe")
            driver.switch_to.frame(frames[idx])
            el = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((by, selector))
            )
            log(f"Campo {selector} encontrado dentro del iframe #{idx}")
            return el
        except Exception:
            continue

    driver.switch_to.default_content()
    return None


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
        except TimeoutException:
            log(f"Timeout cargando la página (intento {intento}). Forzando detención de carga y continuando...")
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

        log("Buscando botón de login (header)...")
        try:
            boton_desplegar = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable(
                    (By.XPATH, '//*[@id="headerLoginButton"]/span | //*[@id="headerLoginButton"]')
                )
            )
            boton_desplegar.click()
            time.sleep(4)
        except Exception:
            log("Botón superior no encontrado, buscando formulario directo...")

        time.sleep(3)
        os.makedirs("data", exist_ok=True)
        driver.save_screenshot("data/pre_fill.png")

        log("Buscando campo de usuario (j_username) en página principal e iframes...")
        campo_user = encontrar_campo(driver, By.ID, "j_username", timeout=20)
        if campo_user is None:
            raise Exception("No se encontró el campo 'j_username' en ningún frame de la página")

        # El iframe puede estar todavía recargando/re-renderizando su contenido
        # en el momento en que encontramos el campo por primera vez. Esperamos
        # y volvemos a buscar referencias "frescas" antes de escribir.
        log("Esperando estabilización del formulario dentro del iframe...")
        time.sleep(4)
        try:
            ready = driver.execute_script("return document.readyState;")
            log(f"document.readyState del frame actual: {ready}")
        except Exception:
            pass

        campo_user = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "j_username"))
        )
        campo_pass = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "j_password"))
        )

        log(f"Atributos j_username -> disabled={campo_user.get_attribute('disabled')}, readonly={campo_user.get_attribute('readonly')}, type={campo_user.get_attribute('type')}, displayed={campo_user.is_displayed()}, enabled={campo_user.is_enabled()}")
        log(f"Atributos j_password -> disabled={campo_pass.get_attribute('disabled')}, readonly={campo_pass.get_attribute('readonly')}, type={campo_pass.get_attribute('type')}, displayed={campo_pass.is_displayed()}, enabled={campo_pass.is_enabled()}")

        log("Escribiendo usuario (vía ActionChains - teclado global, evita problemas de iframe)...")
        driver.execute_script("arguments[0].focus(); arguments[0].value='';", campo_user)
        time.sleep(0.5)
        ActionChains(driver).send_keys(USUARIO).perform()
        time.sleep(0.5)

        log("Escribiendo contraseña (vía ActionChains)...")
        driver.execute_script("arguments[0].focus(); arguments[0].value='';", campo_pass)
        time.sleep(0.5)
        ActionChains(driver).send_keys(PASSWORD).perform()
        time.sleep(0.5)

        # Tab para disparar validación/blur del framework
        ActionChains(driver).send_keys(Keys.TAB).perform()
        time.sleep(1)

        val_user = campo_user.get_attribute("value")
        val_pass = campo_pass.get_attribute("value")
        log(f"Verificación (Selenium attribute) -> usuario: '{val_user}' (longitud={len(val_user or '')}), password longitud={len(val_pass or '')}")

        if not val_user or not val_pass:
            log("Los campos siguen vacíos tras ActionChains. Probando escritura lenta por elemento como respaldo...")
            campo_user.click()
            time.sleep(0.3)
            campo_user.clear()
            escribir_lento(campo_user, USUARIO)
            time.sleep(0.3)
            campo_pass.click()
            time.sleep(0.3)
            campo_pass.clear()
            escribir_lento(campo_pass, PASSWORD)
            campo_pass.send_keys(Keys.TAB)
            time.sleep(1)
            val_user = campo_user.get_attribute("value")
            val_pass = campo_pass.get_attribute("value")
            log(f"Verificación (escritura lenta) -> usuario: '{val_user}' (longitud={len(val_user or '')}), password longitud={len(val_pass or '')}")

        if not val_user or not val_pass:
            log("Los campos siguen vacíos. Probando inyección JS + eventos como último recurso...")
            set_value_js(driver, "j_username", USUARIO)
            set_value_js(driver, "j_password", PASSWORD)
            time.sleep(1)
            val_user = driver.execute_script("return document.getElementById('j_username') ? document.getElementById('j_username').value : null;")
            val_pass = driver.execute_script("return document.getElementById('j_password') ? document.getElementById('j_password').value : null;")
            log(f"Verificación tras JS -> usuario: '{val_user}' (longitud={len(val_user or '')}), password longitud={len(val_pass or '')}")

        driver.save_screenshot("data/filled.png")

        if not val_user or not val_pass:
            log("ADVERTENCIA: los campos siguen vacíos. Se continúa de todas formas para diagnosticar, pero el login probablemente falle.")

        log("Presionando botón de ingreso...")
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
