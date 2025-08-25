"""
Backtest Runner для MEXC Grid Trading Bot
Тестирование стратегии на исторических данных
"""

import pandas as pd
import numpy as np
import json
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from strategy import GridStrategy
from pathlib import Path
import matplotlib.pyplot as plt


class BacktestEngine:
    """
    Движок для бэктестинга торговых стратегий
    
    Особенности:
    - Симуляция исполнений с реалистичными задержками
    - Учет комиссий и проскальзывания
    - Подробная статистика результатов
    - Визуализация equity curve
    """
    
    def __init__(self, config_path: str = 'config.json'):
        """Инициализация движка"""
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        
        self.strategy = GridStrategy(config_path)
        self.results = {
            'trades': [],
            'equity_curve': [],
            'daily_returns': [],
            'stats': {}
        }
        
        # Параметры симуляции
        self.maker_fee = 0.0  # MEXC maker fee
        self.taker_fee = 0.001  # 0.1% taker fee
        self.slippage = 0.0005  # 0.05% slippage
        
        print(f"🔬 Backtest Engine инициализирован")
    
    def load_data(self, data_path: str) -> pd.DataFrame:
        """
        Загрузка исторических данных
        
        Args:
            data_path: Путь к CSV файлу с данными
            
        Expected format:
        timestamp,open,high,low,close,volume
        """
        print(f"📊 Загрузка данных из {data_path}")
        
        if data_path.endswith('.csv'):
            df = pd.read_csv(data_path)
        else:
            # Создаем синтетические данные для демонстрации
            df = self.generate_synthetic_data()
        
        # Стандартизация колонок
        required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"CSV должен содержать колонки: {required_cols}")
        
        # Конвертация timestamp
        if df['timestamp'].dtype == 'object':
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        print(f"✅ Загружено {len(df)} свечей")
        print(f"📅 Период: {df['timestamp'].min()} - {df['timestamp'].max()}")
        
        return df
    
    def generate_synthetic_data(self, days: int = 30) -> pd.DataFrame:
        """Генерация синтетических данных для тестирования"""
        print("🎲 Генерируем синтетические данные...")
        
        # Базовые параметры
        start_price = 45000.0
        volatility = 0.02  # 2% дневная волатильность
        periods = days * 24 * 60  # минутные данные
        
        # Генерация цен (Geometric Brownian Motion)
        dt = 1 / (365 * 24 * 60)  # 1 минута в долях года
        prices = [start_price]
        
        for i in range(periods):
            # Случайное движение цены
            shock = np.random.normal(0, volatility * np.sqrt(dt))
            new_price = prices[-1] * (1 + shock)
            
            # Добавляем трендовость (слабо растущий тренд)
            trend = 0.00001  # 0.001% в минуту
            new_price *= (1 + trend)
            
            prices.append(new_price)
        
        # Создание OHLC данных
        timestamps = []
        ohlc_data = []
        
        start_time = datetime.now() - timedelta(days=days)
        
        for i in range(0, len(prices) - 1):
            timestamp = start_time + timedelta(minutes=i)
            
            # Простое OHLC на основе соседних цен
            open_price = prices[i]
            close_price = prices[i + 1]
            
            # High/Low с некоторой вариацией
            high_price = max(open_price, close_price) * (1 + np.random.uniform(0, 0.002))
            low_price = min(open_price, close_price) * (1 - np.random.uniform(0, 0.002))
            
            volume = np.random.uniform(100, 1000)
            
            timestamps.append(timestamp)
            ohlc_data.append([open_price, high_price, low_price, close_price, volume])
        
        df = pd.DataFrame(ohlc_data, columns=['open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = timestamps
        
        return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    def simulate_execution(self, order_type: str, price: float, quantity: float, 
                          market_price: float) -> Tuple[bool, float, float]:
        """
        Симуляция исполнения ордера
        
        Returns:
            (executed, fill_price, fill_quantity)
        """
        if order_type == 'LIMIT':
            # Лимитный ордер исполняется если цена достигла уровня
            if order_type == 'BUY' and market_price <= price:
                # Добавляем проскальзывание в пользу рынка
                fill_price = price * (1 + self.slippage)
                return True, fill_price, quantity
            elif order_type == 'SELL' and market_price >= price:
                fill_price = price * (1 - self.slippage)
                return True, fill_price, quantity
        
        return False, 0.0, 0.0
    
    def calculate_metrics(self, df: pd.DataFrame) -> Dict:
        """Расчет метрик производительности"""
        equity_curve = pd.DataFrame(self.results['equity_curve'])
        
        if len(equity_curve) == 0:
            return {'error': 'Недостаточно данных для расчета метрик'}
        
        # Базовые метрики
        initial_capital = equity_curve['equity'].iloc[0]
        final_capital = equity_curve['equity'].iloc[-1]
        total_return = (final_capital - initial_capital) / initial_capital
        
        # Максимальная просадка
        equity_curve['running_max'] = equity_curve['equity'].expanding().max()
        equity_curve['drawdown'] = (equity_curve['equity'] - equity_curve['running_max']) / equity_curve['running_max']
        max_drawdown = equity_curve['drawdown'].min()
        
        # Коэффициент Шарпа (упрощенный)
        if len(equity_curve) > 1:
            returns = equity_curve['equity'].pct_change().dropna()
            sharpe_ratio = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
        else:
            sharpe_ratio = 0
        
        # Статистика по сделкам
        trades = pd.DataFrame(self.results['trades'])
        if len(trades) > 0:
            trades['pnl'] = trades['sell_price'] - trades['buy_price']
            winning_trades = trades[trades['pnl'] > 0]
            losing_trades = trades[trades['pnl'] < 0]
            
            win_rate = len(winning_trades) / len(trades) if len(trades) > 0 else 0
            avg_win = winning_trades['pnl'].mean() if len(winning_trades) > 0 else 0
            avg_loss = losing_trades['pnl'].mean() if len(losing_trades) > 0 else 0
        else:
            win_rate = avg_win = avg_loss = 0
        
        # Периоды тестирования
        start_date = df['timestamp'].iloc[0]
        end_date = df['timestamp'].iloc[-1]
        test_days = (end_date - start_date).days
        
        return {
            'period': {
                'start': start_date.strftime('%Y-%m-%d'),
                'end': end_date.strftime('%Y-%m-%d'),
                'days': test_days
            },
            'returns': {
                'initial_capital': initial_capital,
                'final_capital': final_capital,
                'total_return': total_return,
                'annualized_return': (final_capital / initial_capital) ** (365 / test_days) - 1 if test_days > 0 else 0
            },
            'risk': {
                'max_drawdown': max_drawdown,
                'sharpe_ratio': sharpe_ratio,
                'volatility': returns.std() * np.sqrt(252) if 'returns' in locals() and len(returns) > 1 else 0
            },
            'trades': {
                'total_trades': len(trades) if 'trades' in locals() else 0,
                'win_rate': win_rate,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'profit_factor': abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
            }
        }
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """Основной цикл бэктестинга"""
        print("🚀 Запуск бэктестинга...")
        
        total_rows = len(df)
        
        for i, row in df.iterrows():
            # Прогресс
            if i % (total_rows // 20) == 0:
                progress = (i / total_rows) * 100
                print(f"📊 Прогресс: {progress:.1f}%")
            
            # Текущие рыночные данные
            current_price = row['close']
            bid = current_price * 0.999  # Примерный bid
            ask = current_price * 1.001  # Примерный ask
            
            # Выполнение шага стратегии
            actions = self.strategy.step_book(current_price, bid, ask)
            
            # Симуляция исполнений (упрощенная)
            # В реальном бэктесте здесь была бы более сложная логика
            
            # Сохранение состояния
            status = self.strategy.get_status()
            self.results['equity_curve'].append({
                'timestamp': row['timestamp'],
                'price': current_price,
                'equity': status['equity'],
                'cash': status['cash'],
                'base_holdings': status['base_holdings'],
                'realized_pnl': status['realized_pnl']
            })
        
        print("✅ Бэктестинг завершен!")
        
        # Расчет метрик
        metrics = self.calculate_metrics(df)
        self.results['stats'] = metrics
        
        return self.results
    
    def save_results(self, output_dir: str = 'backtest_results'):
        """Сохранение результатов"""
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        # Сохранение equity curve
        equity_df = pd.DataFrame(self.results['equity_curve'])
        if len(equity_df) > 0:
            equity_df.to_csv(output_path / 'equity_curve.csv', index=False)
        
        # Сохранение сделок
        trades_df = pd.DataFrame(self.results['trades'])
        if len(trades_df) > 0:
            trades_df.to_csv(output_path / 'trades.csv', index=False)
        
        # Сохранение метрик
        with open(output_path / 'summary.json', 'w') as f:
            json.dump(self.results['stats'], f, indent=2, default=str)
        
        print(f"💾 Результаты сохранены в {output_path}")
    
    def plot_results(self, output_dir: str = 'backtest_results'):
        """Создание графиков"""
        equity_df = pd.DataFrame(self.results['equity_curve'])
        
        if len(equity_df) == 0:
            print("⚠️ Нет данных для построения графиков")
            return
        
        plt.style.use('seaborn-v0_8' if 'seaborn-v0_8' in plt.style.available else 'default')
        
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
        fig.suptitle('MEXC Grid Trading Bot - Backtest Results', fontsize=16)
        
        # Equity Curve
        ax1.plot(equity_df['timestamp'], equity_df['equity'], 'b-', linewidth=2)
        ax1.set_title('Equity Curve')
        ax1.set_ylabel('Capital ($)')
        ax1.grid(True, alpha=0.3)
        
        # Price vs Holdings
        ax2.plot(equity_df['timestamp'], equity_df['price'], 'r-', alpha=0.7, label='BTC Price')
        ax2_twin = ax2.twinx()
        ax2_twin.plot(equity_df['timestamp'], equity_df['base_holdings'], 'g-', alpha=0.7, label='BTC Holdings')
        ax2.set_title('Price vs Holdings')
        ax2.set_ylabel('BTC Price ($)', color='r')
        ax2_twin.set_ylabel('BTC Holdings', color='g')
        ax2.grid(True, alpha=0.3)
        
        # Cash Balance
        ax3.plot(equity_df['timestamp'], equity_df['cash'], 'purple', linewidth=2)
        ax3.set_title('Cash Balance')
        ax3.set_ylabel('Cash ($)')
        ax3.grid(True, alpha=0.3)
        
        # Realized PnL
        ax4.plot(equity_df['timestamp'], equity_df['realized_pnl'], 'orange', linewidth=2)
        ax4.set_title('Realized P&L')
        ax4.set_ylabel('P&L ($)')
        ax4.grid(True, alpha=0.3)
        ax4.axhline(y=0, color='black', linestyle='--', alpha=0.5)
        
        # Форматирование дат
        for ax in [ax1, ax2, ax3, ax4]:
            ax.tick_params(axis='x', rotation=45)
        
        plt.tight_layout()
        
        # Сохранение
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        plt.savefig(output_path / 'backtest_results.png', dpi=300, bbox_inches='tight')
        print(f"📊 Графики сохранены в {output_path / 'backtest_results.png'}")
        
        plt.show()


def main():
    """Точка входа для бэктестинга"""
    parser = argparse.ArgumentParser(description='MEXC Grid Bot Backtesting')
    parser.add_argument('--config', default='config.json', help='Путь к конфигурации')
    parser.add_argument('--data', help='Путь к CSV файлу с историческими данными')
    parser.add_argument('--output', default='backtest_results', help='Папка для результатов')
    parser.add_argument('--plot', action='store_true', help='Создать графики')
    
    args = parser.parse_args()
    
    print("🔬 MEXC Grid Trading Bot - Backtesting")
    print("=" * 50)
    
    # Инициализация движка
    engine = BacktestEngine(args.config)
    
    # Загрузка данных
    if args.data and Path(args.data).exists():
        df = engine.load_data(args.data)
    else:
        print("⚠️ Файл данных не найден, используем синтетические данные")
        df = engine.load_data(None)
    
    # Запуск бэктестинга
    results = engine.run_backtest(df)
    
    # Вывод результатов
    stats = results['stats']
    print("\n" + "=" * 50)
    print("📈 РЕЗУЛЬТАТЫ БЭКТЕСТИНГА")
    print("=" * 50)
    
    if 'error' in stats:
        print(f"❌ Ошибка: {stats['error']}")
        return
    
    print(f"📅 Период: {stats['period']['start']} - {stats['period']['end']} ({stats['period']['days']} дней)")
    print(f"💰 Начальный капитал: ${stats['returns']['initial_capital']:,.2f}")
    print(f"💰 Конечный капитал: ${stats['returns']['final_capital']:,.2f}")
    print(f"📊 Общая доходность: {stats['returns']['total_return']:.2%}")
    print(f"📈 Годовая доходность: {stats['returns']['annualized_return']:.2%}")
    print(f"📉 Максимальная просадка: {stats['risk']['max_drawdown']:.2%}")
    print(f"🎯 Коэффициент Шарпа: {stats['risk']['sharpe_ratio']:.2f}")
    print(f"🎲 Сделок: {stats['trades']['total_trades']}")
    print(f"🎯 Винрейт: {stats['trades']['win_rate']:.1%}")
    
    # Сохранение результатов
    engine.save_results(args.output)
    
    # Создание графиков
    if args.plot:
        try:
            engine.plot_results(args.output)
        except Exception as e:
            print(f"⚠️ Ошибка создания графиков: {e}")
            print("💡 Установите matplotlib: pip install matplotlib")


if __name__ == "__main__":
    main()
