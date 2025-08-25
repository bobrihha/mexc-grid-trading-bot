"""
Secure Live Runner для MEXC Grid Trading Bot
Версия с безопасным хранением API ключей
"""

import time
import json
import os
import asyncio
from datetime import datetime
from typing import Dict, Optional
import logging
from pathlib import Path
from strategy import GridStrategy, OrderType
from mexc_api import MexcAPIClient, MockMexcAPIClient

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_secure.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class SecureLiveTradingBot:
    """
    Безопасная версия торгового бота с защищенным хранением API ключей
    """
    
    def __init__(self, config_path: str = 'config.json'):
        """
        Инициализация бота
        
        Args:
            config_path: Путь к основной конфигурации
        """
        self.config_path = config_path
        self.running = False
        
        # Загрузка основной конфигурации
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        # Инициализация стратегии
        self.strategy = GridStrategy(config_path)
        
        # Инициализация API клиента
        self.api_client = self._init_api_client()
        
        # Переменные состояния
        self.last_price = 0.0
        self.poll_interval = self.config['runtime']['poll_seconds']
        self.symbol = self.config['runtime']['symbol']
        
        logger.info(f"🤖 Безопасный бот инициализирован для {self.symbol}")
    
    def _init_api_client(self):
        """Инициализация API клиента с безопасным получением ключей"""
        
        # Сначала спрашиваем режим
        print("\n🔐 MEXC Grid Trading Bot - Secure Mode")
        print("=" * 50)
        
        while True:
            print("\nВыберите режим работы:")
            print("1 - 🧪 Mock (безопасное тестирование)")
            print("2 - 🔗 Live (реальная торговля с API файлом)")
            print("3 - ⌨️  Live (интерактивный ввод API)")
            
            choice = input("\nВыбор (1/2/3): ").strip()
            
            if choice == '1':
                logger.info("🧪 Используется MOCK режим")
                return MockMexcAPIClient()
            
            elif choice == '2':
                return self._init_from_file()
            
            elif choice == '3':
                return self._init_interactive()
            
            else:
                print("❌ Неверный выбор. Попробуйте еще раз.")
    
    def _init_from_file(self):
        """Инициализация API из файла с ключами"""
        api_file = 'api_keys.json'
        
        if not os.path.exists(api_file):
            print(f"\n❌ Файл {api_file} не найден!")
            print("📋 Создайте файл по образцу api_keys_template.json:")
            print("   1. cp api_keys_template.json api_keys.json")
            print("   2. Отредактируйте api_keys.json с вашими ключами")
            print("   3. Запустите бота снова")
            exit(1)
        
        try:
            with open(api_file, 'r') as f:
                api_config = json.load(f)
            
            mexc_config = api_config['mexc']
            api_key = mexc_config['api_key']
            api_secret = mexc_config['api_secret']
            testnet = mexc_config.get('testnet', True)
            
            # Проверка что ключи заполнены
            if api_key == "YOUR_MEXC_API_KEY_HERE" or api_secret == "YOUR_MEXC_API_SECRET_HERE":
                print("❌ Пожалуйста, замените YOUR_MEXC_API_KEY_HERE на реальные ключи в api_keys.json")
                exit(1)
            
            logger.info("🔗 Подключение к MEXC API из файла конфигурации")
            if testnet:
                logger.warning("⚠️ Используется TESTNET режим")
            
            return MexcAPIClient(api_key, api_secret, testnet=testnet)
            
        except Exception as e:
            print(f"❌ Ошибка загрузки API ключей: {e}")
            exit(1)
    
    def _init_interactive(self):
        """Интерактивный ввод API ключей"""
        print("\n🔑 Интерактивный ввод API ключей")
        print("⚠️ ВНИМАНИЕ: Ключи будут видны при вводе!")
        
        api_key = input("Введите MEXC API Key: ").strip()
        api_secret = input("Введите MEXC API Secret: ").strip()
        
        if not api_key or not api_secret:
            print("❌ API ключи не могут быть пустыми!")
            exit(1)
        
        testnet_choice = input("Использовать testnet? (y/n): ").strip().lower()
        testnet = testnet_choice in ['y', 'yes', 'да', '1']
        
        logger.info("🔗 Подключение к MEXC API (интерактивный режим)")
        if testnet:
            logger.warning("⚠️ Используется TESTNET режим")
        
        return MexcAPIClient(api_key, api_secret, testnet=testnet)
    
    def get_market_data(self) -> Dict:
        """Получение рыночных данных"""
        try:
            # Получение цены
            price_data = self.api_client.ticker_price(self.symbol)
            current_price = float(price_data['price'])
            
            # Получение книги ордеров
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
            # Возвращаем последнюю известную цену или fallback
            fallback_price = self.last_price if self.last_price > 0 else 45000.0
            return {
                'price': fallback_price,
                'bid': fallback_price * 0.999,
                'ask': fallback_price * 1.001,
                'timestamp': datetime.now()
            }
    
    def execute_orders(self, actions: Dict):
        """Выполнение торговых действий"""
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
    
    def log_status(self, market_data: Dict):
        """Логирование статуса"""
        status = self.strategy.get_status()
        
        logger.info("=" * 50)
        logger.info(f"💰 Баланс: ${status['cash']:.2f} | BTC: {status['base_holdings']:.6f}")
        logger.info(f"📊 Капитал: ${status['equity']:.2f} | P&L: {status['realized_pnl']:.2f}")
        logger.info(f"📋 Ордера: {status['active_orders']} | Позиции: {status['positions']}")
        logger.info(f"💹 Цена: ${market_data['price']:.2f} | Просадка: {status['drawdown']:.1%}")
        logger.info("=" * 50)
    
    async def run_strategy_cycle(self):
        """Один цикл стратегии"""
        # 1. Получение рыночных данных
        market_data = self.get_market_data()
        self.last_price = market_data['price']
        
        # 2. Выполнение стратегии
        actions = self.strategy.step_book(
            current_price=market_data['price'],
            bid=market_data['bid'],
            ask=market_data['ask']
        )
        
        # 3. Обработка сообщений
        for message in actions.get('messages', []):
            logger.info(f"🧠 Стратегия: {message}")
        
        # 4. Выполнение торговых действий
        if actions.get('place_orders') or actions.get('cancel_orders'):
            self.execute_orders(actions)
        
        # 5. Логирование каждые 5 циклов
        if hasattr(self, 'cycle_count'):
            self.cycle_count += 1
        else:
            self.cycle_count = 1
            
        if self.cycle_count % 5 == 0:
            self.log_status(market_data)
    
    def run(self):
        """Основной цикл бота"""
        logger.info("🚀 Запуск MEXC Grid Trading Bot (Secure)...")
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
        logger.info("✅ Бот остановлен")


def main():
    """Точка входа"""
    print("🔐 MEXC Grid Trading Bot - Secure Edition")
    
    # Создание .gitignore если его нет
    if not os.path.exists('.gitignore'):
        with open('.gitignore', 'w') as f:
            f.write("api_keys.json\n")
            f.write("*.log\n")
            f.write("__pycache__/\n")
        print("✅ Создан .gitignore для защиты API ключей")
    
    # Запуск бота
    bot = SecureLiveTradingBot()
    bot.run()


if __name__ == "__main__":
    main()
