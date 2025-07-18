import requests
import tkinter as tk
import pandas as pd
from tkinter import messagebox
import os

def main():
    csvconfig()
    # messagebox.showinfo("Info", "Baixando CSV...")
    uf = input("UF:")
    cidade = input("Cidade:")
    dados_filtrados = filtrar_por_cidade_mem("../resources/CNEAS_API.csv", uf, cidade)
    if dados_filtrados is not None:
        # print(dados_filtrados)
        nomes = dados_filtrados["cneas_entidade_razao_social_s"].tolist()
        print(nomes)  # Exemplo: mostrar as primeiras linhas
        # Você pode usar 'dados_filtrados' em outras funções do seu programa


def csvconfig():
    # CONFIGURAÇÃO
    API_KEY = os.environ.get("CNEAS_API_KEY")
    if not API_KEY:
        print("❌ API key not found. Please set the CNEAS_API_KEY environment variable.")
        exit()
    DATASET_ID = "cneas--cadastro-nacional-de-entidades-de-assistencia-social"
    NOME_ARQUIVO = "../resources/CNEAS_API.csv"

    # 1. Obter detalhes do conjunto de dados
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

    # 2. Filtrar apenas recursos CSV de ENTIDADES
    recursos = data.get("recursos", [])
    csvs_entidades = [
        r for r in recursos
        if "entidades" in r["titulo"].lower() and r["formato"].lower() == "csv"
    ]

    # 3. Selecionar o mais recente pelo título (ex: 2024 primeiro)
    csvs_entidades.sort(key=lambda r: r["titulo"], reverse=True)
    recurso_mais_recente = csvs_entidades[0]

    link_csv = recurso_mais_recente["link"]
    print(f"📥 Baixando: {recurso_mais_recente['titulo']}")
    print(f"🌐 Link: {link_csv}")

    # 4. Fazer download
    os.makedirs(os.path.dirname(NOME_ARQUIVO), exist_ok=True)
    response_csv = requests.get(link_csv)
    with open(NOME_ARQUIVO, "wb") as f:
        f.write(response_csv.content)

    print(f"✅ Arquivo salvo como: {NOME_ARQUIVO}")

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

if __name__ == "__main__":
    main()