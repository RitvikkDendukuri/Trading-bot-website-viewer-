import logging
from pathlib import Path
import pandas as pd
import yfinance as yf

macroFile = Path("macro.csv")
pricesFile = Path("sector_prices.csv")

coreTickers = {
    "consumer": "XLY",
    "labor": "SPY",
    "inflation": "XLE",
    "credit": "XLF",
}

sectorTickers = list(set([
    "XLY", "XLI", "XLF", "XHB", "IWM", "XLK", "QQQ", "SPY",
    "QQQ", "XLK", "SMH", "IGV", "XLY", "XLC", "SPY",
    "XLF", "XLI", "XLB", "XME", "IWM", "XLY", "SPY",
    "XLE", "XOP", "XME", "XLB", "DBC", "GLD", "SPY",
    "XLE", "GLD", "DBC", "XLP", "XLU", "TIP", "XLV",
    "XLV", "XLP", "XLU", "USMV", "TLT", "IEF", "GLD",
    "TLT", "IEF", "SHY", "GLD", "UUP"
]))

extraTickers = {
    "vix": "^VIX",
    "ten_year": "^TNX",
    "three_mo": "^IRX",
}

# --- FUNCTIONS DEFINED FIRST ---

def transformCore(name: str, series: pd.Series) -> pd.Series:
    if name == "consumer":
        return series.pct_change(63) * 100
    if name == "labor":
        return series.pct_change(126) * 100
    if name == "inflation":
        return series.pct_change(126) * 100
    if name == "credit":
        return -series.pct_change(63) * 100
    return series

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

def downloadSeries(ticker: str) -> pd.Series:
    logging.info(f"Downloading {ticker}...")
    df = yf.download(ticker, start="1999-01-01", interval="1d", progress=False, auto_adjust=False)
    
    if df is None or df.empty:
        logging.warning(f"No data for {ticker}")
        return None

    if isinstance(df.columns, pd.MultiIndex):
        if "Adj Close" in df.columns.get_level_values(0):
            df = df["Adj Close"]
        elif "Close" in df.columns.get_level_values(0):
            df = df["Close"]
        else:
            df = df.iloc[:, 0]
    elif "Adj Close" in df.columns:
        df = df["Adj Close"]
    elif "Close" in df.columns:
        df = df["Close"]
    
    if isinstance(df, pd.DataFrame):
        df = df.iloc[:, 0]

    s = df.dropna()
    s.name = ticker
    return s

def buildMacro():
    logging.info("Starting update...")

    allTickers = set(coreTickers.values()) | set(extraTickers.values()) | set(sectorTickers)
    rawData = {}
    
    for t in sorted(list(allTickers)):
        s = downloadSeries(t)
        if s is not None:
            rawData[t] = s

    logging.info("Building Macro Indicators...")
    macroCols = {}
    
    for name, ticker in coreTickers.items():
        if ticker in rawData:
            macroCols[name] = transformCore(name, rawData[ticker])
            
    if "^TNX" in rawData and "^IRX" in rawData:
        ty = rawData["^TNX"]
        tm = rawData["^IRX"]
        ty, tm = ty.align(tm, join='inner')
        macroCols["yield_curve"] = ty - tm
        
    if "^VIX" in rawData:
        macroCols["volatility"] = rawData["^VIX"]

    dfMacro = pd.DataFrame(macroCols)
    dfMacro = dfMacro.sort_index().ffill()
    
    dfMacro = dfMacro.dropna()
    dfMacro = dfMacro.resample("D").ffill()
    
    dfMacro.to_csv(macroFile)
    logging.info(f"Saved {macroFile} (Start: {dfMacro.index.min()}, Cols: {len(dfMacro.columns)})")

    logging.info("Building Sector Prices...")
    
    priceCols = {}
    for t in sectorTickers:
        if t in rawData:
            priceCols[t] = rawData[t]
            
    dfPrices = pd.DataFrame(priceCols)
    dfPrices = dfPrices.sort_index().ffill()
    
    dfPrices = dfPrices.loc[dfPrices.index >= dfMacro.index.min()]
    dfPrices = dfPrices.resample("D").ffill()

    dfPrices.to_csv(pricesFile)
    logging.info(f"Saved {pricesFile} (Start: {dfPrices.index.min()}, Cols: {len(dfPrices.columns)})")
    
    print(f"1. Macro Regimes: {macroFile}")
    print(f"2. Asset Prices:  {pricesFile}")


# --- ALIASES MOVED HERE (AFTER DEFINITIONS) ---
MACRO_FILE = macroFile
PRICES_FILE = pricesFile
CORE_TICKERS = coreTickers
SECTOR_TICKERS = sectorTickers
EXTRA_TICKERS = extraTickers
transform_core = transformCore
download_series = downloadSeries
build_macro = buildMacro

if __name__ == "__main__":
    buildMacro()