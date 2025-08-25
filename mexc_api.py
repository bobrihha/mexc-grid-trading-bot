"""
MEXC API клиент для выполнения торговых операций
"""

import requests
import hashlib
import hmac
import time
from typing import Dict, List, Optional
import json


class MexcAPIClient:
    """
    API клиент для биржи MEXC

    Поддерживает:
    - Получение информации о парах
    - Размещение и отмена ордеров
    - Получение баланса и позиций
    """

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        """
        Инициализация API клиента

        Args:
            api_key: API ключ
            api_secret: Секретный ключ
            testnet: Использовать тестнет (по умолчанию True для безопасности)
        """
        self.api_key = api_key
        self.api_secret = api_secret.encode()

        if testnet:
            self.base_url = (
                "https://api.mexc.com/api/v3"  # MEXC не имеет публичного testnet
            )
            print(
                "⚠️ ВНИМАНИЕ: MEXC не предоставляет публичный testnet. Будьте осторожны!"
            )
        else:
            self.base_url = "https://api.mexc.com/api/v3"

        self.session = requests.Session()
        self.session.headers.update({"X-MEXC-APIKEY": api_key})

    def _generate_signature(self, query_string: str) -> str:
        """Генерация подписи для аутентификации"""
        return hmac.new(
            self.api_secret, query_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _request(
        self, method: str, endpoint: str, params: Dict = None, signed: bool = False
    ) -> Dict:
        """
        Выполнение HTTP запроса к API

        Args:
            method: HTTP метод (GET, POST, DELETE)
            endpoint: API эндпоинт
            params: Параметры запроса
            signed: Требуется ли подпись
        """
        params = params or {}
        url = f"{self.base_url}{endpoint}"

        if signed:
            params["timestamp"] = int(time.time() * 1000)
            query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
            params["signature"] = self._generate_signature(query_string)

        try:
            if method == "GET":
                response = self.session.get(url, params=params)
            elif method == "POST":
                response = self.session.post(url, params=params)
            elif method == "DELETE":
                response = self.session.delete(url, params=params)
            else:
                raise ValueError(f"Неподдерживаемый HTTP метод: {method}")

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"Ошибка API запроса: {e}")
            if hasattr(e.response, "text"):
                print(f"Ответ сервера: {e.response.text}")
            raise

    def exchange_info(self, symbol: str = None) -> Dict:
        """
        Получение информации о торговых парах

        Args:
            symbol: Торговая пара (например, BTCUSDT)

        Returns:
            Информация о паре включая tick_size, step_size, min_notional
        """
        params = {"symbol": symbol} if symbol else {}
        data = self._request("GET", "/exchangeInfo", params)

        if symbol:
            # Поиск конкретной пары
            for pair in data.get("symbols", []):
                if pair["symbol"] == symbol:
                    # Извлечение важных фильтров
                    filters = {f["filterType"]: f for f in pair["filters"]}

                    return {
                        "symbol": symbol,
                        "status": pair["status"],
                        "tick_size": float(
                            filters.get("PRICE_FILTER", {}).get("tickSize", "0.01")
                        ),
                        "qty_step": float(
                            filters.get("LOT_SIZE", {}).get("stepSize", "0.0001")
                        ),
                        "min_qty": float(
                            filters.get("LOT_SIZE", {}).get("minQty", "0.0001")
                        ),
                        "min_notional": float(
                            filters.get("MIN_NOTIONAL", {}).get("minNotional", "10")
                        ),
                    }
            raise ValueError(f"Торговая пара {symbol} не найдена")

        return data

    def ticker_price(self, symbol: str) -> Dict:
        """
        Получение текущей цены

        Args:
            symbol: Торговая пара

        Returns:
            Текущая цена пары
        """
        params = {"symbol": symbol}
        return self._request("GET", "/ticker/price", params)

    def order_book(self, symbol: str, limit: int = 5) -> Dict:
        """
        Получение книги ордеров

        Args:
            symbol: Торговая пара
            limit: Количество уровней (5, 10, 20, 50, 100, 500, 1000, 5000)

        Returns:
            Книга ордеров с bid/ask
        """
        params = {"symbol": symbol, "limit": limit}
        return self._request("GET", "/depth", params)

    def account_info(self) -> Dict:
        """
        Получение информации об аккаунте и балансах

        Returns:
            Информация об аккаунте включая балансы
        """
        return self._request("GET", "/account", signed=True)

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float = None,
        order_type: str = "LIMIT",
    ) -> Dict:
        """
        Размещение ордера

        Args:
            symbol: Торговая пара
            side: Сторона (BUY/SELL)
            quantity: Количество
            price: Цена (для лимитных ордеров)
            order_type: Тип ордера (MARKET, LIMIT)

        Returns:
            Информация о созданном ордере
        """
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity,
        }

        if order_type == "LIMIT":
            if price is None:
                raise ValueError("Цена обязательна для лимитных ордеров")
            params["price"] = price
            params["timeInForce"] = "GTC"  # Good Till Canceled

        return self._request("POST", "/order", params, signed=True)

    def cancel_order(
        self, symbol: str, order_id: str = None, orig_client_order_id: str = None
    ) -> Dict:
        """
        Отмена ордера

        Args:
            symbol: Торговая пара
            order_id: ID ордера
            orig_client_order_id: Клиентский ID ордера

        Returns:
            Информация об отмененном ордере
        """
        params = {"symbol": symbol}

        if order_id:
            params["orderId"] = order_id
        elif orig_client_order_id:
            params["origClientOrderId"] = orig_client_order_id
        else:
            raise ValueError("Необходимо указать order_id или orig_client_order_id")

        return self._request("DELETE", "/order", params, signed=True)

    def open_orders(self, symbol: str = None) -> List[Dict]:
        """
        Получение активных ордеров

        Args:
            symbol: Торговая пара (если None, то все пары)

        Returns:
            Список активных ордеров
        """
        params = {"symbol": symbol} if symbol else {}
        return self._request("GET", "/openOrders", params, signed=True)

    def order_history(self, symbol: str, limit: int = 50) -> List[Dict]:
        """
        История ордеров

        Args:
            symbol: Торговая пара
            limit: Количество записей

        Returns:
            История ордеров
        """
        params = {"symbol": symbol, "limit": limit}
        return self._request("GET", "/allOrders", params, signed=True)

    def my_trades(self, symbol: str, limit: int = 50) -> List[Dict]:
        """
        История сделок

        Args:
            symbol: Торговая пара
            limit: Количество записей

        Returns:
            История сделок
        """
        params = {"symbol": symbol, "limit": limit}
        return self._request("GET", "/myTrades", params, signed=True)


# Тестовый клиент для демонстрации
class MockMexcAPIClient(MexcAPIClient):
    """
    Мок-клиент для тестирования без реальных API вызовов
    """

    def __init__(self):
        """Инициализация мок-клиента"""
        # Не вызываем родительский __init__ чтобы не требовать API ключи
        self.mock_price = 45000.0
        self.mock_orders = {}
        self.mock_balance = {"USDT": 10000.0, "BTC": 0.22}

        print("🧪 Используется MOCK API клиент (для тестирования)")

    def ticker_price(self, symbol: str) -> Dict:
        """Мок получения цены"""
        return {"symbol": symbol, "price": str(self.mock_price)}

    def order_book(self, symbol: str, limit: int = 5) -> Dict:
        """Мок книги ордеров"""
        return {
            "bids": [[str(self.mock_price - 10), "1.0"]],
            "asks": [[str(self.mock_price + 10), "1.0"]],
        }

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float = None,
        order_type: str = "LIMIT",
    ) -> Dict:
        """Мок размещения ордера"""
        order_id = str(len(self.mock_orders) + 1)

        order = {
            "orderId": order_id,
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": str(quantity),
            "price": str(price) if price else None,
            "status": "NEW",
        }

        self.mock_orders[order_id] = order
        print(f"📋 MOCK: Ордер размещен {side} {quantity} @ {price}")

        return order

    def cancel_order(self, symbol: str, order_id: str = None, **kwargs) -> Dict:
        """Мок отмены ордера"""
        if order_id in self.mock_orders:
            self.mock_orders[order_id]["status"] = "CANCELED"
            print(f"❌ MOCK: Ордер {order_id} отменен")
            return self.mock_orders[order_id]
        else:
            raise ValueError(f"Ордер {order_id} не найден")

    def open_orders(self, symbol: str = None) -> List[Dict]:
        """Мок получения активных ордеров"""
        return [
            order
            for order in self.mock_orders.values()
            if order["status"] == "NEW"
            and (symbol is None or order["symbol"] == symbol)
        ]

    def account_info(self) -> Dict:
        """Мок информации об аккаунте"""
        balances = [
            {"asset": asset, "free": str(amount), "locked": "0.0"}
            for asset, amount in self.mock_balance.items()
        ]

        return {"balances": balances}

    def exchange_info(self, symbol: str = None) -> Dict:
        """Мок информации о паре"""
        if symbol:
            return {
                "symbol": symbol,
                "status": "TRADING",
                "tick_size": 0.01,
                "qty_step": 0.0001,
                "min_qty": 0.0001,
                "min_notional": 10.0,
            }
        return {"symbols": []}
