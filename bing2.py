import os
import json
import time
import openai
import pandas as pd
import re
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

openai.api_key = os.environ.get("OPENAI_API_KEY")

# ========== CONFIG ==========
MAX_PAGINAS = 4
MAX_CHARS_HTML = 30000
CACHE_DIR = "resources/cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def csvconfig():
    API_KEY = os.environ.get("CNEAS_API_KEY")
    if not API_KEY:
        print("❌ API key not found. Please set the CNEAS_API_KEY environment variable.")
        exit()

    DATASET_ID = "cneas--cadastro-nacional-de-entidades-de-assistencia-social"
    ARQUIVO_CSV = "../resources/CNEAS_API.csv"
    ARQUIVO_META = "../resources/CNEAS_API.meta"

    url = f"https://dados.gov.br/dados/api/publico/conjuntos-dados/{DATASET_ID}"
    headers = {
        "accept": "application/json",
        "chave-api-dados-abertos": API_KEY
    }

    print("🔍 Consultando metadados...")
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"❌ Erro ao consultar API: {response.status_code} - {response.reason}\nConteúdo: {response.text}")
        exit()

    data = response.json()
    recursos = data.get("recursos", [])
    csvs_entidades = [
        r for r in recursos
        if "entidades" in r["titulo"].lower() and r["formato"].lower() == "csv"
    ]

    if not csvs_entidades:
        print("⚠️ Nenhum CSV de entidades encontrado.")
        exit()

    csvs_entidades.sort(key=lambda r: r["titulo"], reverse=True)
    recurso_mais_recente = csvs_entidades[0]
    titulo_csv = recurso_mais_recente["titulo"]
    link_csv = recurso_mais_recente["link"]

    # Verifica se já existe e se está atualizado
    if os.path.exists(ARQUIVO_CSV) and os.path.exists(ARQUIVO_META):
        with open(ARQUIVO_META, "r") as meta:
            titulo_salvo = meta.read().strip()
        if titulo_csv == titulo_salvo:
            print("✅ Arquivo já está atualizado.")
            return

    # Baixa e salva
    print(f"📥 Baixando: {titulo_csv}")
    print(f"🌐 Link: {link_csv}")
    os.makedirs(os.path.dirname(ARQUIVO_CSV), exist_ok=True)
    response_csv = requests.get(link_csv)
    with open(ARQUIVO_CSV, "wb") as f:
        f.write(response_csv.content)
    with open(ARQUIVO_META, "w") as meta:
        meta.write(titulo_csv)

    print(f"✅ Arquivo salvo como: {ARQUIVO_CSV}")

def filtrar_por_cidade_mem(caminho_csv, uf, cidade):
    df = pd.read_csv(caminho_csv, sep=",", encoding="utf-8")
    col_uf = "cneas_entidade_sigla_uf_s"
    col_cidade = "cneas_entidade_nome_municipio_s"
    filtro = (df[col_uf].str.upper() == uf.upper()) & (df[col_cidade].str.upper() == cidade.upper())
    df_filtrado = df[filtro]
    if df_filtrado.empty:
        print("Nenhuma ONG encontrada para essa cidade.")
        return None
    return df_filtrado

def airanking(uf: str, cidade: str):
    """Retorna as cinco ONGs mais relevantes de uma cidade usando a API da OpenAI."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not found. Please set the environment variable.")
        return []

    openai.api_key = api_key
    prompt = (
        f"Liste as cinco ONGs mais relevantes da cidade de {cidade} - {uf} no Brasil. "
        "Forneça apenas uma lista numerada com os nomes das ONGs."
    )

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        text = response.choices[0].message.content.strip()
        lines = [re.sub(r"^\d+\.\s*", "", l).strip() for l in text.splitlines() if l.strip()]
        return lines[:5]
    except Exception as e:
        print(f"Erro ao consultar OpenAI: {e}")
        return []

# ========== 1. Busca no Bing ==========
def get_links_bing(cidade, uf, limite=10):
    query = f"ongs {cidade} {uf}"
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get(f"https://www.bing.com/search?q={query}")
        time.sleep(2)
        results = driver.find_elements(By.CSS_SELECTOR, "li.b_algo")
        links = []
        for r in results:
            try:
                a = r.find_element(By.TAG_NAME, "a")
                title = a.text.strip()
                url = a.get_attribute("href")
                if title and url and "bing.com" not in url:
                    links.append({"title": title, "url": url})
                if len(links) >= limite:
                    break
            except:
                continue
        return links
    finally:
        driver.quit()

# ========== 2. Planejamento via IA ==========
def planejar_visitas_com_ia(links):
    prompt = (
        "Você receberá uma lista de títulos e URLs sobre ONGs em uma cidade.\n"
        "Escolha até 4 URLs que provavelmente contenham listas de ONGs reais.\n"
        "Responda em JSON no formato: [{\"url\": ..., \"motivo\": ...}]\n\n"
        "Lista:\n" + "\n".join(f"{l['title']} - {l['url']}" for l in links)
    )

    try:
        resp = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        resposta = resp.choices[0].message.content.strip()
        return json.loads(resposta)
    except Exception as e:
        print(f"Erro no planejamento com IA: {e}")
        return []

# ========== 3. Extração de HTML ==========
def extrair_html_limpo(driver, url):
    try:
        driver.get(url)
        time.sleep(2)
        for tag in ["main", "section", "body"]:
            try:
                el = driver.find_element(By.TAG_NAME, tag)
                html = el.get_attribute("innerText")
                if html:
                    return html.strip()[:MAX_CHARS_HTML]
            except:
                continue
        return ""
    except Exception as e:
        print(f"Erro ao acessar {url}: {e}")
        return ""

# ========== 4. IA extrai nomes do HTML ==========
def extrair_nomes_com_ia(html, url):
    prompt = (
        f"Extraia apenas nomes de ONGs que estejam sediadas em {cidade.upper()} - {uf.upper()}.\n"
        f"Ignore quaisquer ONGs de outras cidades.\n"
        f"Aqui está o conteúdo da página ({url}):\n\n"
        + html[:MAX_CHARS_HTML]
    )

    try:
        resp = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        if resp and resp.choices and resp.choices[0].message and resp.choices[0].message.content:
            texto = resp.choices[0].message.content.strip()
        else:
            print("❌ Resposta inválida da OpenAI.")
            return []
        return [l.strip("- ") for l in texto.splitlines() if l.strip()]
    except Exception as e:
        print(f"Erro ao extrair nomes com IA: {e}")
        return []

# ========== Função principal ==========
def processar_cidade(uf, cidade):
    nome_arquivo = f"{CACHE_DIR}/{uf.lower()}_{cidade.lower()}.json"
    if os.path.exists(nome_arquivo):
        with open(nome_arquivo, "r") as f:
            # print("✅ Resultado carregado do cache.")
            return json.load(f)

    print(f"🔎 Processando {cidade} - {uf}...")
    links = get_links_bing(cidade, uf, limite=10)
    plano = planejar_visitas_com_ia(links)

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    try:
        nomes_final = []
        for item in plano[:MAX_PAGINAS]:
            url = item.get("url")
            if not url:
                continue
            print(f"🌐 Visitando: {url}")
            html = extrair_html_limpo(driver, url)
            if html:
                nomes = extrair_nomes_com_ia(html, url)
                nomes_final.extend(nomes)
        nomes_final = list(sorted(set(nomes_final)))
        with open(nome_arquivo, "w") as f:
            json.dump(nomes_final, f, indent=2, ensure_ascii=False)
        # print(f"✅ {len(nomes_final)} ONGs salvas em cache.")
        return nomes_final
    finally:
        driver.quit()

# Exemplo de uso
if __name__ == "__main__":
    uf = input("UF: ")
    cidade = input("Cidade: ")
    ongs_ai = airanking(uf, cidade)
    print ("ONGs IA:")
    for nome in ongs_ai:
        print("-", nome)
    ongs = processar_cidade(uf, cidade)
    print ("ONGs Scraping:")
    for nomes in ongs:
        print("-", nomes)
    print ("ONGs CNEAS:")
    dados_filtrados = filtrar_por_cidade_mem("../resources/CNEAS_API.csv", uf, cidade)
    if dados_filtrados is not None:
        nomes_csv = dados_filtrados["cneas_entidade_nome_fantasia_s"].dropna().unique()
        for nome in nomes_csv:
            print("-", nome)