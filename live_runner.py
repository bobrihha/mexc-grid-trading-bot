"""
Live Runner для MEXC Grid Trading Bot
Основной файл для запуска бота в режиме реальной торговли
"""

import time
import json
import asyncio
from datetime import datetime
from typing import Dict, Optional
import logging
from strategy import GridStrategy, OrderType
from mexc_api import MexcAPIClient, MockMexcAPIClient

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class LiveTradingBot:
    """
    Основной класс для управления live торговлей
    
    Функции:
    - Подключение к MEXC API
    - Выполнение стратегии в реальном времени
    - Управление ордерами и позициями
    - Мониторинг и логирование
    """
    
    def __init__(self, config_path: str = 'config.json', use_mock: bool = True):
        """
        Инициализация торгового бота
        
        Args:
            config_path: Путь к файлу конфигурации
            use_mock: Использовать mock-клиент (True для безопасности)
        """
        self.config_path = config_path
        self.use_mock = use_mock
        self.running = False
        
        # Загрузка конфигурации
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        # Инициализация стратегии
        self.strategy = GridStrategy(config_path)
        
        # Инициализация API клиента
        if use_mock:
            self.api_client = MockMexcAPIClient()
            logger.info("🧪 Используется MOCK API для безопасного тестирования")
        else:
            # Для реального использования нужны API ключи
            api_key = input("Введите MEXC API Key: ")
            api_secret = input("Введите MEXC API Secret: ")
            self.api_client = MexcAPIClient(api_key, api_secret, testnet=True)
            logger.info("🔗 Подключение к реальному MEXC API")
        
        # Переменные состояния
        self.last_price = 0.0
        self.poll_interval = self.config['runtime']['poll_seconds']
        self.symbol = self.config['runtime']['symbol']
        
        logger.info(f"🤖 Бот инициализирован для {self.symbol}")
    
    def get_market_data(self) -> Dict:
        """Получение текущих рыночных данных"""
        try:
            # Получение цены
            price_data = self.api_client.ticker_price(self.symbol)
            current_price = float(price_data['price'])
            
            # Получение книги ордеров для bid/ask
            orderbook = self.api_client.order_book(self.symbol, limit=5)
            
            best_bid = float(orderbook['bids'][0][0]) if orderbook['bids'] else current_price
            best_ask = float(orderbook['asks'][0][0]) if orderbook['asks'] else current_price
            
            return {
                'price': current_price,
                'bid': best_bid,
                'ask': best_ask,
                'timestamp': datetime.now()
            }
            
        except Exception as e:
            logger.error(f"Ошибка получения рыночных данных: {e}")
            # Возвращаем последнюю известную цену
            return {
                'price': self.last_price if self.last_price > 0 else 45000.0,
                'bid': self.last_price * 0.999 if self.last_price > 0 else 44950.0,
                'ask': self.last_price * 1.001 if self.last_price > 0 else 45050.0,
                'timestamp': datetime.now()
            }
    
    def execute_orders(self, actions: Dict):
        """
        Выполнение действий по размещению/отмене ордеров
        
        Args:
            actions: Словарь с действиями от стратегии
        """
        # Размещение новых ордеров
        for order in actions.get('place_orders', []):
            try:
                logger.info(f"📋 Размещаем {order.side.value}: {order.quantity} @ {order.price}")
                
                result = self.api_client.place_order(
                    symbol=order.symbol,
                    side=order.side.value,
                    quantity=order.quantity,
                    price=order.price,
                    order_type='LIMIT'
                )
                
                # Обновляем ID ордера в стратегии
                order.id = result.get('orderId', order.id)
                logger.info(f"✅ Ордер размещен: {order.id}")
                
            except Exception as e:
                logger.error(f"❌ Ошибка размещения ордера {order.id}: {e}")
        
        # Отмена ордеров
        for order_id in actions.get('cancel_orders', []):
            try:
                logger.info(f"❌ Отменяем ордер: {order_id}")
                
                self.api_client.cancel_order(
                    symbol=self.symbol,
                    order_id=order_id
                )
                
                logger.info(f"✅ Ордер отменен: {order_id}")
                
            except Exception as e:
                logger.error(f"❌ Ошибка отмены ордера {order_id}: {e}")
    
    def check_fills(self):
        """Проверка исполнения ордеров"""
        try:
            # Получаем историю недавних сделок
            recent_trades = self.api_client.my_trades(self.symbol, limit=10)
            
            for trade in recent_trades:
                # Обрабатываем новые исполнения
                self.strategy.on_order_filled(
                    order_id=trade.get('orderId'),
                    fill_price=float(trade.get('price')),
                    fill_quantity=float(trade.get('qty'))
                )
                
        except Exception as e:
            logger.error(f"Ошибка проверки исполнений: {e}")
    
    def reconcile_orders(self):
        """Синхронизация состояния ордеров с биржей"""
        try:
            # Получаем активные ордера с биржи
            exchange_orders = self.api_client.open_orders(self.symbol)
            exchange_order_ids = {order['orderId'] for order in exchange_orders}
            
            # Проверяем ордера в стратегии
            strategy_order_ids = set(self.strategy.active_orders.keys())
            
            # Находим расхождения
            missing_on_exchange = strategy_order_ids - exchange_order_ids
            extra_on_exchange = exchange_order_ids - strategy_order_ids
            
            if missing_on_exchange:
                logger.warning(f"Ордера отсутствуют на бирже: {missing_on_exchange}")
                # Удаляем из стратегии
                for order_id in missing_on_exchange:
                    if order_id in self.strategy.active_orders:
                        del self.strategy.active_orders[order_id]
            
            if extra_on_exchange:
                logger.warning(f"Лишние ордера на бирже: {extra_on_exchange}")
                # Можем отменить или проигнорировать
            
        except Exception as e:
            logger.error(f"Ошибка синхронизации ордеров: {e}")
    
    def log_status(self, market_data: Dict):
        """Логирование текущего статуса бота"""
        status = self.strategy.get_status()
        
        logger.info("=" * 50)
        logger.info(f"💰 Баланс: ${status['cash']:.2f} | BTC: {status['base_holdings']:.6f}")
        logger.info(f"📊 Капитал: ${status['equity']:.2f} | P&L: {status['realized_pnl']:.2f}")
        logger.info(f"📋 Ордера: {status['active_orders']} | Позиции: {status['positions']}")
        logger.info(f"💹 Цена: ${market_data['price']:.2f} | Просадка: {status['drawdown']:.1%}")
        logger.info("=" * 50)
    
    async def run_strategy_cycle(self):
        """Один цикл выполнения стратегии"""
        # 1. Получение рыночных данных
        market_data = self.get_market_data()
        self.last_price = market_data['price']
        
        # 2. Проверка исполнений
        self.check_fills()
        
        # 3. Выполнение логики стратегии
        actions = self.strategy.step_book(
            current_price=market_data['price'],
            bid=market_data['bid'],
            ask=market_data['ask']
        )
        
        # 4. Обработка сообщений от стратегии
        for message in actions.get('messages', []):
            logger.info(f"🧠 Стратегия: {message}")
        
        # 5. Выполнение торговых действий
        if actions.get('place_orders') or actions.get('cancel_orders'):
            self.execute_orders(actions)
        
        # 6. Синхронизация каждые 10 циклов
        if hasattr(self, 'cycle_count'):
            self.cycle_count += 1
        else:
            self.cycle_count = 1
            
        if self.cycle_count % 10 == 0:
            self.reconcile_orders()
        
        # 7. Логирование каждые 5 циклов
        if self.cycle_count % 5 == 0:
            self.log_status(market_data)
    
    def run(self):
        """Основной цикл бота"""
        logger.info("🚀 Запуск MEXC Grid Trading Bot...")
        self.running = True
        
        try:
            while self.running:
                asyncio.run(self.run_strategy_cycle())
                time.sleep(self.poll_interval)
                
        except KeyboardInterrupt:
            logger.info("🛑 Получен сигнал остановки (Ctrl+C)")
            self.stop()
        except Exception as e:
            logger.error(f"💥 Критическая ошибка: {e}")
            self.stop()
    
    def stop(self):
        """Остановка бота"""
        logger.info("🔴 Остановка бота...")
        self.running = False
        
        # Отменяем все активные ордера
        try:
            active_orders = self.api_client.open_orders(self.symbol)
            for order in active_orders:
                self.api_client.cancel_order(self.symbol, order['orderId'])
                logger.info(f"❌ Отменен ордер: {order['orderId']}")
        except Exception as e:
            logger.error(f"Ошибка отмены ордеров при остановке: {e}")
        
        logger.info("✅ Бот остановлен")
    
    def get_status_dict(self) -> Dict:
        """Получение статуса для веб-интерфейса"""
        return {
            'running': self.running,
            'last_price': self.last_price,
            'strategy_status': self.strategy.get_status(),
            'use_mock': self.use_mock,
            'symbol': self.symbol
        }


def main():
    """Точка входа для запуска бота"""
    print("🤖 MEXC Grid Trading Bot")
    print("=" * 50)
    
    # Выбор режима
    while True:
        mode = input("Выберите режим:\n1 - Mock (безопасное тестирование)\n2 - Live (реальная торговля)\nВвод (1/2): ").strip()
        
        if mode == '1':
            use_mock = True
            break
        elif mode == '2':
            use_mock = False
            print("⚠️ ВНИМАНИЕ: Реальная торговля! Убедитесь в правильности настроек!")
            confirm = input("Продолжить? (yes/no): ").strip().lower()
            if confirm == 'yes':
                break
        else:
            print("Неверный ввод. Попробуйте снова.")
    
    # Запуск бота
    bot = LiveTradingBot(use_mock=use_mock)
    bot.run()


if __name__ == "__main__":
    main()
