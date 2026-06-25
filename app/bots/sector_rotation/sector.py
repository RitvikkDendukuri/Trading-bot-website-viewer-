from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Dict, Optional, Tuple
import numpy as np
import pandas as pd


macroColumnAliases: Dict[str, Tuple[str, ...]] = {
    "consumer": ("consumer", "Consumer", "xrt", "XRT", "XLY", "xly"),
    "labor": ("labor", "Labor", "employment", "VTI", "vti", "SPY", "spy"),
    "inflation": ("inflation", "Inflation", "infl", "TIP", "tip", "XLE", "xle"),
    "credit": ("credit", "Credit", "stress", "HYG", "hyg", "XLF", "xlf"),
}


class EconomicRegime(Enum):
    RECOVERY = auto()
    GOLDILOCKS = auto()
    REFLATION = auto()
    OVERHEAT = auto()
    STAGFLATION = auto()
    SLOWDOWN = auto()
    CRISIS = auto()


@dataclass
class MacroIndicatorConfig:
    consumerWeight: float = 0.30
    laborWeight: float = 0.20
    inflationWeight: float = 0.25
    creditWeight: float = 0.25
    zscoreWindow: int = 365
    thresholdWindow: int = 365
    smoothingWindow: int = 14


@dataclass
class PortfolioConfig:
    maxWeightPerSector: float = 0.25
    transactionCostBps: float = 5.0
    rebalanceFrequency: str = "D"
    targetVol: float = 0.18
    volLookbackDays: int = 63
    maxLeverage: float = 2.0
    minLeverage: float = 0.5


class MacroRegimeDetector:
    def __init__(self, config: MacroIndicatorConfig):
        self.config = config

    def normalizeMacroInputs(self, df: pd.DataFrame) -> pd.DataFrame:
        cols = df.columns
        mapping: Dict[str, str] = {}
        for stdName, aliases in macroColumnAliases.items():
            for col in cols:
                if col in aliases:
                    mapping[col] = stdName
                    break

        dfNorm = df.rename(columns=mapping).copy()
        required = ["consumer", "labor", "inflation", "credit"]

        window = self.config.zscoreWindow
        for col in required:
            if col in dfNorm.columns:
                rollMean = dfNorm[col].rolling(window=window, min_periods=30).mean()
                rollStd = dfNorm[col].rolling(window=window, min_periods=30).std()
                dfNorm[col] = (dfNorm[col] - rollMean) / (rollStd + 1e-6)
            else:
                dfNorm[col] = 0.0

        return dfNorm

    def computeCompositeScores(self, df: pd.DataFrame) -> pd.DataFrame:
        cfg = self.config
        scores = pd.DataFrame(index=df.index)
        scores["growth"] = df["consumer"] * cfg.consumerWeight + df["labor"] * cfg.laborWeight
        scores["inflation_pressure"] = df["inflation"] * cfg.inflationWeight

        scores["financial_stress"] = -1.0 * df["credit"] * cfg.creditWeight
        return scores

    def computeQuantiles(
        self, series: pd.Series, quantiles: List[float], window: int
    ) -> Dict[float, Dict[pd.Timestamp, float]]:
        q_dict: Dict[float, Dict[pd.Timestamp, float]] = {q: {} for q in quantiles}
        rolled = series.rolling(window=window, min_periods=max(10, window // 4))
        for q in quantiles:
            q_series = rolled.quantile(q)
            q_dict[q] = q_series.to_dict()
        return q_dict

    def detectRegimeSeries(self, macroDf: pd.DataFrame) -> pd.Series:
        macroDf = self.normalizeMacroInputs(macroDf)
        macroDf = macroDf.dropna(how="any")
        if macroDf.empty:
            return pd.Series(dtype=object, name="regime")

        scores = self.computeCompositeScores(macroDf)
        window = max(90, int(getattr(self.config, "thresholdWindow", 365)))

        growth_q = self.computeQuantiles(scores["growth"], [0.25, 0.5, 0.7], window)
        infl_q = self.computeQuantiles(scores["inflation_pressure"], [0.4, 0.7], window)
        stress_q = self.computeQuantiles(scores["financial_stress"], [0.2], window)

        regimes = []
        for dt, row in scores.iterrows():
            g = row["growth"]
            i = row["inflation_pressure"]
            s = row["financial_stress"]

            g_low = growth_q[0.25].get(dt, 0.0)
            g_mid = growth_q[0.5].get(dt, 0.0)
            g_high = growth_q[0.7].get(dt, 0.0)
            i_mid = infl_q[0.4].get(dt, 0.0)
            i_high = infl_q[0.7].get(dt, 0.0)
            s_low = stress_q[0.2].get(dt, 0.0)

            if s < s_low:
                regime = EconomicRegime.CRISIS
            elif g > g_high and i <= i_mid:
                regime = EconomicRegime.GOLDILOCKS
            elif g > g_mid and i > i_high:
                regime = EconomicRegime.OVERHEAT
            elif g <= g_low and i > i_mid:
                regime = EconomicRegime.STAGFLATION
            elif g <= g_low and i <= i_mid:
                regime = EconomicRegime.SLOWDOWN
            elif g > g_mid:
                regime = EconomicRegime.REFLATION
            else:
                regime = EconomicRegime.RECOVERY

            regimes.append(regime)

        return pd.Series(regimes, index=scores.index, name="regime")

    def detectRegimeSeriesSmoothed(self, macroDf: pd.DataFrame) -> pd.Series:
        raw = self.detectRegimeSeries(macroDf)
        window = getattr(self.config, "smoothingWindow", 14)

        all_regimes = list(EconomicRegime)
        regimeToInt = {r: i for i, r in enumerate(all_regimes)}
        intToRegime = {i: r for i, r in enumerate(all_regimes)}

        mapped = raw.map(regimeToInt)

        def rollingMode(x: np.ndarray) -> float:
            vals, counts = np.unique(x, return_counts=True)
            if len(counts) == 0:
                return x[-1]
            return float(vals[np.argmax(counts)])

        smoothedInt = mapped.rolling(window=window, min_periods=1).apply(
            rollingMode, raw=True
        )
        smoothed = smoothedInt.map(lambda v: intToRegime[int(v)])
        return smoothed.rename("regime")

class SectorMapper:


    def __init__(self):
        self.mapping: Dict[EconomicRegime, List[str]] = {

            EconomicRegime.RECOVERY: [
                "XLY", "XLI", "XLF", "XHB", "IWM", "XLK", "QQQ", "SPY",
            ],

            EconomicRegime.GOLDILOCKS: [
                "QQQ", "XLK", "SMH", "IGV", "XLY", "XLC", "SPY",
            ],

            EconomicRegime.REFLATION: [
                "XLF", "XLI", "XLB", "XME", "IWM", "XLY", "SPY",
            ],

            EconomicRegime.OVERHEAT: [
                "XLE", "XOP", "XME", "XLB", "DBC", "GLD", "SPY",
            ],

            EconomicRegime.STAGFLATION: [
                "XLE", "GLD", "DBC", "XLP", "XLU", "TIP", "XLV",
            ],

            EconomicRegime.SLOWDOWN: [
                "XLV", "XLP", "XLU", "USMV", "TLT", "IEF", "GLD",
            ],

            EconomicRegime.CRISIS: [
                "TLT", "IEF", "SHY", "GLD", "UUP",
            ],
        }

    def getSessionsForRegime(self, regime: EconomicRegime) -> List[str]:
        return self.mapping.get(regime, [])


class AssetFilters:
    def __init__(
        self,
        momentumLookback: int = 126,
        rsLookback: int = 63,
        maxVolPercentile: float = 0.90,
    ):
        self.momLb = momentumLookback
        self.rsLb = rsLookback
        self.maxVolPct = maxVolPercentile

    def filterAssets(
        self,
        prices: pd.DataFrame,
        benchmark: Optional[pd.Series] = None,
        topN: Optional[int] = None,
    ) -> List[str]:
        if prices.empty:
            return []


        rets = prices.pct_change().dropna()
        vols = rets.std()
        volCut = vols.quantile(self.maxVolPct)
        safeCols = vols[vols <= volCut].index
        sub = prices[safeCols]
        if sub.empty:
            sub = prices


        momLb = min(self.momLb, len(sub) - 1)
        rsLb = min(self.rsLb, len(sub) - 1)
        if momLb <= 0:
            return list(sub.columns[: topN]) if topN else list(sub.columns)

        momMain = sub.pct_change(momLb).iloc[-1]
        momFast = sub.pct_change(rsLb).iloc[-1]

        baseScore = 0.6 * momMain + 0.4 * momFast

        if benchmark is not None and len(benchmark) > rsLb:
            benchRet = benchmark.pct_change(rsLb).iloc[-1]
            rsScore = momFast - benchRet
            score = 0.7 * baseScore + 0.3 * rsScore
        else:
            score = baseScore

        score = score.replace([np.inf, -np.inf], np.nan).fillna(-1e9)
        score = score.sort_values(ascending=False)

        if topN:
            return list(score.head(topN).index)
        return list(score.index)


class PortfolioConstructor:
    def __init__(self, config: PortfolioConfig):
        self.config = config

    def buildPortfolio(
        self,
        tickers: List[str],
        scores: Optional[pd.Series] = None
    ) -> Dict[str, float]:

        if not tickers:
            return {}

        if scores is not None:

            s = scores.reindex(tickers).fillna(-1e9)
            s = s.clip(lower=0.0)

            total = s.sum()
            if total > 0:
                s = s / total
                return s.to_dict()

        n = len(tickers)
        w = 1.0 / n
        return {t: w for t in tickers}


class Backtester:
    def __init__(
        self,
        prices: pd.DataFrame,
        regimeSeries: pd.Series,
        sectorMapper: SectorMapper,
        assetFilters: AssetFilters,
        portfolioConstructor: PortfolioConstructor,
        portfolioConfig: PortfolioConfig,
    ):
        self.prices = prices
        self.regimes = regimeSeries
        self.mapper = sectorMapper
        self.filters = assetFilters
        self.pc = portfolioConstructor
        self.cfg = portfolioConfig

    def turnover(self, old: Dict[str, float], new: Dict[str, float]) -> float:
        allTickers = set(old.keys()) | set(new.keys())
        chg = 0.0
        for t in allTickers:
            chg += abs(new.get(t, 0.0) - old.get(t, 0.0))
        return chg / 2.0

    def run(self, initialCapital: float = 1_000_000.0):
        dates = self.prices.index
        regimes = self.regimes.reindex(dates).ffill()


        rebalDates = set(self.prices.resample(self.cfg.rebalanceFrequency).last().index)

        equity = pd.Series(index=dates, dtype=float)
        equity.iloc[0] = initialCapital

        tradeLog = []
        weights: Dict[str, float] = {}
        lastRegime: Optional[EconomicRegime] = None

        # per-day timeline so callers can reconstruct intraday (hourly) equity
        self.weightsTimeline: Dict[pd.Timestamp, Dict[str, float]] = {}
        self.levTimeline: Dict[pd.Timestamp, float] = {}

        bench = self.prices["SPY"] if "SPY" in self.prices.columns else None


        rawRets = pd.Series(index=dates, dtype=float)
        rawRets.iloc[0] = 0.0

        for i in range(1, len(dates)):
            d = dates[i]
            prevD = dates[i - 1]
            regime = regimes.loc[d]

            isRebal = d in rebalDates or weights == {} or regime != lastRegime

            turnover = 0.0
            if isRebal and pd.notna(regime):
                cand = self.mapper.getSessionsForRegime(regime)


                valid = [t for t in cand if t in self.prices.columns and not pd.isna(self.prices.at[d, t])]
                if valid:
                    startIdx = max(0, i - 260)
                    windowPrices = self.prices[valid].iloc[startIdx : i + 1]
                    windowBench = bench.iloc[startIdx : i + 1] if bench is not None else None

                    topN = int(1.0 / self.cfg.maxWeightPerSector)
                    chosen = self.filters.filterAssets(
                        windowPrices, benchmark=windowBench, topN=topN
                    )

                    if chosen:
                        sub = windowPrices[chosen]

                        momLb = min(self.filters.momLb, len(sub) - 1)
                        rsLb = min(self.filters.rsLb, len(sub) - 1)

                        if momLb > 0 and rsLb > 0:
                            momMain = sub.pct_change(momLb).iloc[-1]
                            momFast = sub.pct_change(rsLb).iloc[-1]
                            scores = 0.6 * momMain + 0.4 * momFast
                            newWeights = self.pc.buildPortfolio(chosen, scores=scores)
                        else:
                           newWeights = self.pc.buildPortfolio(chosen)
                    else:
                        newWeights = {}
                else:
                    newWeights = {}

                turnover = self.turnover(weights, newWeights)
                weights = newWeights
                lastRegime = regime

                if turnover > 0:
                    tradeLog.append(
                        {
                            "date": d,
                            "event_type": "rebalance",
                            "regime": regime.name if isinstance(regime, EconomicRegime) else str(regime),
                            "tickers": ", ".join(weights.keys()),
                            "turnover": turnover,
                            "value": equity.iloc[i - 1],
                        }
                    )

            portRet = 0.0
            if weights:
                tickers = [t for t in weights.keys() if t in self.prices.columns]
                if tickers:
                    pToday = self.prices.loc[d, tickers]
                    pPrev = self.prices.loc[prevD, tickers]
                    rets = (pToday / pPrev) - 1.0
                    rets = rets.replace([np.inf, -np.inf], 0.0).fillna(0.0)
                    portRet = float(sum(weights[t] * rets[t] for t in tickers))

            if turnover > 0:
                cost = turnover * self.cfg.transactionCostBps / 10_000.0
                portRet -= cost

            rawRets.iloc[i] = portRet

            lev = 1.0
            lb = self.cfg.volLookbackDays
            if i > lb:
                window = rawRets.iloc[i - lb + 1 : i + 1]
                realized_vol = window.std() * np.sqrt(252)
                if realized_vol > 0:
                    lev = self.cfg.targetVol / realized_vol
                    lev = max(self.cfg.minLeverage, min(self.cfg.maxLeverage, lev))

            leveredRet = portRet * lev
            leveredRet = max(leveredRet, -0.95)  # equity can never go non-positive
            equity.iloc[i] = equity.iloc[i - 1] * (1.0 + leveredRet)

            self.weightsTimeline[d] = dict(weights)
            self.levTimeline[d] = lev

        tradeLogDf = pd.DataFrame(tradeLog)
        if not tradeLogDf.empty:
            tradeLogDf.set_index("date", inplace=True)

        return equity.to_frame(name="equity"), tradeLogDf


def runPipeline(
    macroDf: pd.DataFrame, priceDf: pd.DataFrame
):

    macroCfg = MacroIndicatorConfig()
    detector = MacroRegimeDetector(macroCfg)
    regimes = detector.detectRegimeSeriesSmoothed(macroDf)

    sectorMapper = SectorMapper()
    assetFilters = AssetFilters()
    portCfg = PortfolioConfig()
    constructor = PortfolioConstructor(portCfg)

    backtester = Backtester(
        prices=priceDf,
        regimeSeries=regimes,
        sectorMapper=sectorMapper,
        assetFilters=assetFilters,
        portfolioConstructor=constructor,
        portfolioConfig=portCfg,
    )

    equityCurve, tradeLog = backtester.run(initialCapital=1_000_000.0)
    return equityCurve, regimes, tradeLog