# optional Alpaca paper trading client — mirrors rebalances if keys are set
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

DEFAULT_BASE_URL = "https://paper-api.alpaca.markets"
MIN_ORDER_NOTIONAL = 5.0


class AlpacaError(RuntimeError):
    pass


class AlpacaClient:
    def __init__(self, env_prefix: str = "ALPACA"):
        self.env_prefix = env_prefix
        self.api_key = os.environ.get(f"{env_prefix}_API_KEY", "")
        self.api_secret = os.environ.get(f"{env_prefix}_API_SECRET", "")
        self.base_url = os.environ.get(
            f"{env_prefix}_BASE_URL", DEFAULT_BASE_URL
        ).rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _headers(self) -> Dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, json_body: Optional[dict] = None) -> Any:
        if not self.configured:
            raise AlpacaError(f"{self.env_prefix} API credentials not set.")
        resp = requests.request(
            method,
            self.base_url + path,
            headers=self._headers(),
            json=json_body,
            timeout=15,
        )
        if resp.status_code >= 300:
            raise AlpacaError(f"Alpaca {resp.status_code}: {resp.text}")
        return resp.json() if resp.text else {}

    def get_account(self) -> dict:
        return self._request("GET", "/v2/account")

    def get_equity(self) -> float:
        return float(self.get_account()["equity"])

    def get_positions(self) -> List[dict]:
        return self._request("GET", "/v2/positions")

    def cancel_all_orders(self) -> None:
        self._request("DELETE", "/v2/orders")

    def submit_order(self, order: dict) -> dict:
        return self._request("POST", "/v2/orders", json_body=order)

    def sync_to_weights(self, target_weights: Dict[str, float]) -> float:
        try:
            self.cancel_all_orders()
        except AlpacaError:
            pass

        account = self.get_account()
        equity = float(account["equity"])
        if not target_weights:
            return equity

        current = {
            p["symbol"]: {
                "market_value": float(p.get("market_value", 0.0)),
                "qty": float(p.get("qty", 0.0)),
            }
            for p in self.get_positions()
        }

        orders: List[dict] = []
        for sym, weight in target_weights.items():
            tgt_val = weight * equity
            cur_val = current.get(sym, {}).get("market_value", 0.0)
            delta = tgt_val - cur_val
            if abs(delta) < MIN_ORDER_NOTIONAL:
                continue
            orders.append(
                {
                    "symbol": sym,
                    "side": "buy" if delta > 0 else "sell",
                    "type": "market",
                    "time_in_force": "day",
                    "notional": str(round(abs(delta), 2)),
                }
            )

        for sym, pos in current.items():
            if sym not in target_weights and pos["market_value"] > MIN_ORDER_NOTIONAL:
                orders.append(
                    {
                        "symbol": sym,
                        "side": "sell",
                        "type": "market",
                        "time_in_force": "day",
                        "qty": str(pos["qty"]),
                    }
                )

        for order in orders:
            try:
                self.submit_order(order)
            except AlpacaError:
                pass
        return equity
