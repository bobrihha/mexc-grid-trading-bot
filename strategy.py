"""
MEXC Grid Trading Strategy - Основная логика стратегии
Поддерживает плавающую сетку с анти-накоплением и компаундингом
"""

import json
import math
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class OrderType(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    NEW = "NEW"
    FILLED = "FILLED"
    CANCELED = "CANCELED"


@dataclass
class Order:
    """Представление ордера"""

    id: str
    symbol: str
    side: OrderType
    price: float
    quantity: float
    status: OrderStatus
    level_key: Optional[str] = None


@dataclass
class Position:
    """Позиция по конкретному уровню сетки"""

    level_price: float
    quantity: float
    buy_price: float
    tp_price: Optional[float] = None
    tp_order_id: Optional[str] = None


class GridStrategy:
    """
    Основная стратегия торговли сеткой (AMG+)

    Особенности:
    - Анти-накопление: один ордер на уровень
    - Компаундинг прибыли
    - Maker-only исполнение
    - Risk management
    """

    def __init__(self, config_path: str):
        """Инициализация стратегии"""
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        # Состояние стратегии
        self.cash = self.config["capital"]["quote_start"]
        self.base_holdings = (
            self.config["capital"]["base_start_quote"] / 45000
        )  # примерная цена BTC

        # Активные ордера и позиции
        self.active_orders: Dict[str, Order] = {}
        self.positions: Dict[str, Position] = {}  # key = normalized_level_price

        # Статистика
        self.total_pnl = 0.0
        self.realized_pnl = 0.0
        self.max_equity = self.cash
        self.max_drawdown = 0.0

        # История цен для ATR
        self.price_history = []

        print(
            f"Стратегия инициализирована: Cash={self.cash:.2f}, Base={self.base_holdings:.6f}"
        )

    def normalize_price(self, price: float) -> float:
        """Нормализация цены к tick_size"""
        tick_size = self.config["grid"]["tick_size"]
        return round(price / tick_size) * tick_size

    def normalize_quantity(self, qty: float) -> float:
        """Нормализация количества к qty_step"""
        qty_step = self.config["grid"]["qty_step"]
        return round(qty / qty_step) * qty_step

    def get_grid_step(self, current_price: float) -> float:
        """Расчет шага сетки в зависимости от режима"""
        if self.config["grid"]["mode"] == "percent":
            return current_price * self.config["grid"]["step_percent"]
        else:  # ATR mode
            if len(self.price_history) < self.config["grid"]["atr_window"]:
                # Fallback к проценту если недостаточно данных
                return current_price * 0.004

            # Простой расчет ATR
            window = self.config["grid"]["atr_window"]
            recent_prices = self.price_history[-window:]
            high_low = [
                abs(p[0] - p[1]) for p in zip(recent_prices[1:], recent_prices[:-1])
            ]
            atr = np.mean(high_low) if high_low else current_price * 0.004

            return atr * self.config["grid"]["atr_k"]

    def calculate_position_size(self, level_index: int, current_price: float) -> float:
        """Расчет размера позиции для уровня"""
        available_cash = self.cash * 0.9  # 90% кэша доступно
        levels_below = self.config["grid"]["levels_below"]

        if self.config["grid"]["sizing_mode"] == "linear":
            # Равномерное распределение
            size_per_level = available_cash / levels_below
        else:  # geometric
            # Геометрическая прогрессия - больше на дальних уровнях
            weights = [1.2**i for i in range(levels_below)]
            total_weight = sum(weights)
            size_per_level = (available_cash / total_weight) * weights[level_index]

        # Применение skew (больше покупаем при низком inventory)
        current_equity = self.cash + self.base_holdings * current_price
        inventory_ratio = (self.base_holdings * current_price) / current_equity
        target_ratio = self.config["capital"]["target_inventory_ratio"]

        if inventory_ratio < target_ratio:
            # Мало базы - увеличиваем размеры
            skew_mult = (
                1
                + (target_ratio - inventory_ratio)
                * self.config["grid"]["skew_strength"]
            )
            size_per_level *= skew_mult

        return size_per_level

    def can_place_buy(
        self, level_price: float, current_price: float
    ) -> Tuple[bool, str]:
        """Проверка возможности размещения buy ордера"""
        # Нормализованный ключ уровня
        level_key = f"{self.normalize_price(level_price):.8f}"

        # Проверка занятости уровня
        if level_key in self.positions:
            return False, f"Уровень {level_key} уже занят позицией"

        # Проверка активных ордеров на этом уровне
        maker_buffer = self.config["grid"]["maker_buffer_frac"]
        order_price = level_price * (1 - maker_buffer)
        order_price_norm = self.normalize_price(order_price)

        for order in self.active_orders.values():
            if (
                order.side == OrderType.BUY
                and abs(order.price - order_price_norm)
                < self.config["grid"]["tick_size"]
            ):
                return (
                    False,
                    f"Уже есть активный buy ордер на уровне {order_price_norm}",
                )

        # Проверка минимального объема
        position_size = self.calculate_position_size(
            0, current_price
        )  # примерный расчет
        quantity = position_size / order_price_norm
        quantity = self.normalize_quantity(quantity)

        min_notional = self.config["grid"]["min_notional"]
        if quantity * order_price_norm < min_notional:
            return (
                False,
                f"Объем {quantity * order_price_norm:.2f} меньше минимального {min_notional}",
            )

        # Проверка достаточности кэша
        if position_size > self.cash:
            return (
                False,
                f"Недостаточно кэша: нужно {position_size:.2f}, доступно {self.cash:.2f}",
            )

        return True, "OK"

    def get_target_levels(self, current_price: float) -> List[float]:
        """Расчет целевых уровней сетки"""
        step = self.get_grid_step(current_price)
        levels = []

        # Уровни ниже цены (для покупок)
        for i in range(1, self.config["grid"]["levels_below"] + 1):
            level = current_price - i * step
            levels.append(level)

        # Уровни выше (если нужны)
        for i in range(1, self.config["grid"]["levels_above"] + 1):
            level = current_price + i * step
            levels.append(level)

        return levels

    def step_book(self, current_price: float, bid: float, ask: float) -> Dict:
        """
        Основной шаг стратегии
        Возвращает действия для исполнения
        """
        actions = {"place_orders": [], "cancel_orders": [], "messages": []}

        # Обновление истории цен для ATR
        self.price_history.append(current_price)
        if len(self.price_history) > self.config["grid"]["atr_window"] * 2:
            self.price_history = self.price_history[
                -self.config["grid"]["atr_window"] :
            ]

        # Проверка risk management
        current_equity = self.cash + self.base_holdings * current_price
        drawdown = (self.max_equity - current_equity) / self.max_equity

        if drawdown > self.config["risk"]["dd_pause_frac"]:
            actions["messages"].append(
                f"ПАУЗА: просадка {drawdown:.1%} превышает лимит {self.config['risk']['dd_pause_frac']:.1%}"
            )
            return actions

        if drawdown > self.config["risk"]["kill_switch_frac"]:
            actions["messages"].append(f"СТОП: критическая просадка {drawdown:.1%}")
            # Здесь должна быть логика экстренного закрытия всех позиций
            return actions

        # Обновление максимума эквити
        if current_equity > self.max_equity:
            self.max_equity = current_equity

        # Расчет целевых уровней
        target_levels = self.get_target_levels(current_price)

        # Размещение новых buy ордеров
        for i, level in enumerate(target_levels):
            if level >= current_price:  # Только уровни ниже цены
                continue

            can_place, reason = self.can_place_buy(level, current_price)
            if can_place:
                # Расчет параметров ордера
                maker_buffer = self.config["grid"]["maker_buffer_frac"]
                order_price = level * (1 - maker_buffer)
                order_price = self.normalize_price(order_price)

                position_size = self.calculate_position_size(i, current_price)
                quantity = position_size / order_price
                quantity = self.normalize_quantity(quantity)

                # Создание ордера
                order_id = f"BUY_{level:.2f}_{len(self.active_orders)}"
                order = Order(
                    id=order_id,
                    symbol=self.config["runtime"]["symbol"],
                    side=OrderType.BUY,
                    price=order_price,
                    quantity=quantity,
                    status=OrderStatus.NEW,
                    level_key=f"{self.normalize_price(level):.8f}",
                )

                actions["place_orders"].append(order)
                self.active_orders[order_id] = order
                actions["messages"].append(
                    f"Размещен BUY: {quantity:.4f} @ {order_price:.2f}"
                )

        return actions

    def on_order_filled(self, order_id: str, fill_price: float, fill_quantity: float):
        """Обработка исполнения ордера"""
        if order_id not in self.active_orders:
            print(f"Неизвестный ордер: {order_id}")
            return

        order = self.active_orders[order_id]
        order.status = OrderStatus.FILLED

        if order.side == OrderType.BUY:
            self._handle_buy_fill(order, fill_price, fill_quantity)
        else:
            self._handle_sell_fill(order, fill_price, fill_quantity)

        # Удаляем исполненный ордер
        del self.active_orders[order_id]

    def _handle_buy_fill(self, order: Order, fill_price: float, fill_quantity: float):
        """Обработка исполнения покупки"""
        # Списание кэша
        cost = fill_price * fill_quantity
        self.cash -= cost
        self.base_holdings += fill_quantity

        # Создание позиции
        level_key = order.level_key or f"{fill_price:.8f}"
        position = Position(
            level_price=fill_price, quantity=fill_quantity, buy_price=fill_price
        )

        # Расчет цены тейк-профита
        if self.config["grid"]["tp_mode"] == "step":
            step = self.get_grid_step(fill_price)
            tp_price = fill_price + step
        else:  # percent
            tp_price = fill_price * (1 + self.config["grid"]["tp_percent"])

        position.tp_price = self.normalize_price(tp_price)
        self.positions[level_key] = position

        print(
            f"BUY заполнен: {fill_quantity:.4f} @ {fill_price:.2f}, TP @ {position.tp_price:.2f}"
        )
        print(f"Баланс: Cash={self.cash:.2f}, Base={self.base_holdings:.6f}")

        # TODO: Размещение TP ордера через внешний интерфейс

    def _handle_sell_fill(self, order: Order, fill_price: float, fill_quantity: float):
        """Обработка исполнения продажи (TP)"""
        # Поиск соответствующей позиции
        position_key = None
        for key, pos in self.positions.items():
            if pos.tp_order_id == order.id:
                position_key = key
                break

        if position_key:
            position = self.positions[position_key]

            # Расчет прибыли
            profit = (fill_price - position.buy_price) * fill_quantity
            self.realized_pnl += profit
            self.total_pnl += profit

            # Возврат в кэш (компаундинг)
            if self.config["capital"]["compound"]:
                self.cash += fill_price * fill_quantity

            # Уменьшение базовых активов
            self.base_holdings -= fill_quantity

            # Удаление позиции
            del self.positions[position_key]

            print(
                f"TP заполнен: {fill_quantity:.4f} @ {fill_price:.2f}, прибыль: {profit:.2f}"
            )
            print(f"Реализованная прибыль: {self.realized_pnl:.2f}")

    def get_status(self) -> Dict:
        """Получение текущего статуса стратегии"""
        current_equity = self.cash + self.base_holdings * 45000  # примерная цена

        return {
            "cash": self.cash,
            "base_holdings": self.base_holdings,
            "equity": current_equity,
            "realized_pnl": self.realized_pnl,
            "total_pnl": self.total_pnl,
            "max_equity": self.max_equity,
            "drawdown": (self.max_equity - current_equity) / self.max_equity,
            "active_orders": len(self.active_orders),
            "positions": len(self.positions),
            "config": self.config,
        }
