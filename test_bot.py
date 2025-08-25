#!/usr/bin/env python3
"""
Быстрый тест всех компонентов MEXC Grid Trading Bot
"""

def test_strategy():
    """Тест стратегии"""
    print("🧪 Тестирование GridStrategy...")
    
    try:
        from strategy import GridStrategy
        
        # Создание стратегии
        strategy = GridStrategy('config.json')
        
        # Получение статуса
        status = strategy.get_status()
        print(f"✅ Стратегия: Cash=${status['cash']:.2f}, BTC={status['base_holdings']:.6f}")
        
        # Тест шага стратегии
        actions = strategy.step_book(45000.0, 44950.0, 45050.0)
        print(f"✅ Создано {len(actions['place_orders'])} ордеров")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка стратегии: {e}")
        return False


def test_api_client():
    """Тест API клиента"""
    print("\n🔗 Тестирование API клиента...")
    
    try:
        from mexc_api import MockMexcAPIClient
        
        # Создание mock клиента
        client = MockMexcAPIClient()
        
        # Тест получения цены
        price_data = client.ticker_price('BTCUSDT')
        print(f"✅ Цена BTC: ${float(price_data['price']):,.2f}")
        
        # Тест размещения ордера
        order = client.place_order('BTCUSDT', 'BUY', 0.001, 44000.0)
        print(f"✅ Ордер размещен: {order['orderId']}")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка API: {e}")
        return False


def test_web_interface():
    """Тест веб-интерфейса"""
    print("\n🌐 Тестирование веб-интерфейса...")
    
    try:
        from app import app
        print("✅ FastAPI приложение загружено")
        
        # Проверка эндпоинтов
        routes = [route.path for route in app.routes]
        print(f"✅ Доступно {len(routes)} маршрутов: {routes[:3]}...")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка веб-интерфейса: {e}")
        return False


def test_live_runner():
    """Тест live runner"""
    print("\n🚀 Тестирование Live Runner...")
    
    try:
        from live_runner import LiveTradingBot
        
        # Создание бота в mock режиме
        bot = LiveTradingBot(use_mock=True)
        status = bot.get_status_dict()
        
        print(f"✅ Live Runner: Symbol={status['symbol']}, Mock={status['use_mock']}")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка Live Runner: {e}")
        return False


def test_backtest():
    """Тест бэктестера"""
    print("\n📊 Тестирование Backtester...")
    
    try:
        from backtest_runner import BacktestEngine
        
        # Создание движка
        engine = BacktestEngine('config.json')
        
        # Генерация тестовых данных
        df = engine.generate_synthetic_data(days=7)  # 7 дней данных
        
        print(f"✅ Backtest Engine: {len(df)} свечей сгенерировано")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка Backtest: {e}")
        return False


def main():
    """Основная функция тестирования"""
    print("🤖 MEXC Grid Trading Bot - Комплексное тестирование")
    print("=" * 60)
    
    tests = [
        ("Стратегия", test_strategy),
        ("API клиент", test_api_client),
        ("Веб-интерфейс", test_web_interface), 
        ("Live Runner", test_live_runner),
        ("Backtester", test_backtest)
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"💥 Критическая ошибка в {name}: {e}")
            results.append((name, False))
    
    # Итоговый отчет
    print("\n" + "=" * 60)
    print("📋 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
    print("=" * 60)
    
    passed = 0
    for name, success in results:
        status = "✅ ПРОЙДЕН" if success else "❌ ПРОВАЛЕН"
        print(f"{name:15} | {status}")
        if success:
            passed += 1
    
    total = len(results)
    print(f"\n🎯 ИТОГО: {passed}/{total} тестов пройдено ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("\n🎉 ВСЕ КОМПОНЕНТЫ РАБОТАЮТ КОРРЕКТНО!")
        print("🚀 Бот готов к использованию!")
        print("\n💡 Для запуска:")
        print("   • Веб-интерфейс: python3 app.py")
        print("   • Live торговля: python3 live_runner.py") 
        print("   • Бэктестинг: python3 backtest_runner.py --plot")
    else:
        print(f"\n⚠️  {total-passed} компонент(ов) требуют исправления")
    
    return passed == total


if __name__ == "__main__":
    main()
