"""
FastAPI веб-интерфейс для управления MEXC торговым ботом
"""

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import json
import os
from typing import Dict, Any
from strategy import GridStrategy
import uvicorn

app = FastAPI(title="MEXC Grid Trading Bot", version="1.0.0")

# Глобальное состояние бота
bot_strategy: GridStrategy = None
bot_running = False

# HTML шаблоны (встроенные)
index_template = """
<!DOCTYPE html>
<html>
<head>
    <title>MEXC Grid Trading Bot</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        .card { background: white; padding: 20px; margin: 20px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .status { padding: 10px; border-radius: 4px; margin: 10px 0; }
        .running { background-color: #d4edda; color: #155724; }
        .stopped { background-color: #f8d7da; color: #721c24; }
        .btn { padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; margin: 5px; }
        .btn-success { background-color: #28a745; color: white; }
        .btn-danger { background-color: #dc3545; color: white; }
        .form-group { margin: 15px 0; }
        .form-group label { display: block; margin-bottom: 5px; font-weight: bold; }
        .form-group input, select { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }
        .stat-item { text-align: center; }
        .stat-value { font-size: 24px; font-weight: bold; color: #007bff; }
        .stat-label { color: #666; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 MEXC Grid Trading Bot</h1>
        
        <div class="card">
            <h2>Статус бота</h2>
            <div class="status {{ 'running' if bot_running else 'stopped' }}">
                {{ 'ЗАПУЩЕН ✅' if bot_running else 'ОСТАНОВЛЕН ⏸️' }}
            </div>
            
            {% if bot_running %}
            <form method="post" action="/stop" style="display: inline;">
                <button type="submit" class="btn btn-danger">Остановить бота</button>
            </form>
            {% else %}
            <form method="post" action="/start" style="display: inline;">
                <button type="submit" class="btn btn-success">Запустить бота</button>
            </form>
            {% endif %}
        </div>

        {% if status %}
        <div class="card">
            <h2>Финансовые показатели</h2>
            <div class="stats">
                <div class="stat-item">
                    <div class="stat-value">${{ "%.2f"|format(status.cash) }}</div>
                    <div class="stat-label">Наличные (USDT)</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{{ "%.6f"|format(status.base_holdings) }}</div>
                    <div class="stat-label">BTC</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${{ "%.2f"|format(status.equity) }}</div>
                    <div class="stat-label">Общий капитал</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{{ "%.2f"|format(status.realized_pnl) }}</div>
                    <div class="stat-label">Реализованная прибыль</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{{ status.active_orders }}</div>
                    <div class="stat-label">Активные ордера</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{{ status.positions }}</div>
                    <div class="stat-label">Открытые позиции</div>
                </div>
            </div>
        </div>
        {% endif %}

        <div class="card">
            <h2>Настройки стратегии</h2>
            <form method="post" action="/update_config">
                <div class="form-group">
                    <label>Торговая пара:</label>
                    <input type="text" name="symbol" value="{{ config.runtime.symbol }}" required>
                </div>
                
                <div class="form-group">
                    <label>Режим сетки:</label>
                    <select name="grid_mode">
                        <option value="percent" {{ 'selected' if config.grid.mode == 'percent' else '' }}>Процентный</option>
                        <option value="atr" {{ 'selected' if config.grid.mode == 'atr' else '' }}>ATR</option>
                    </select>
                </div>
                
                <div class="form-group">
                    <label>Шаг сетки (%):</label>
                    <input type="number" name="step_percent" value="{{ config.grid.step_percent }}" step="0.001" min="0.001" required>
                </div>
                
                <div class="form-group">
                    <label>Режим тейк-профита:</label>
                    <select name="tp_mode">
                        <option value="step" {{ 'selected' if config.grid.tp_mode == 'step' else '' }}>Один шаг</option>
                        <option value="percent" {{ 'selected' if config.grid.tp_mode == 'percent' else '' }}>Процент</option>
                    </select>
                </div>
                
                <div class="form-group">
                    <label>Тейк-профит (%):</label>
                    <input type="number" name="tp_percent" value="{{ config.grid.tp_percent }}" step="0.001" min="0.001">
                </div>
                
                <div class="form-group">
                    <label>Уровней ниже цены:</label>
                    <input type="number" name="levels_below" value="{{ config.grid.levels_below }}" min="1" max="50" required>
                </div>
                
                <div class="form-group">
                    <label>Стартовый капитал (USDT):</label>
                    <input type="number" name="quote_start" value="{{ config.capital.quote_start }}" min="100" required>
                </div>
                
                <div class="form-group">
                    <label>
                        <input type="checkbox" name="compound" {{ 'checked' if config.capital.compound else '' }}>
                        Включить компаундинг
                    </label>
                </div>
                
                <button type="submit" class="btn btn-success">Сохранить настройки</button>
            </form>
        </div>
    </div>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Главная страница с дашбордом"""
    global bot_strategy, bot_running

    # Загрузка конфигурации
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    # Получение статуса бота
    status = None
    if bot_strategy:
        status = bot_strategy.get_status()

    # Рендеринг с использованием Jinja2
    from jinja2 import Template

    template = Template(index_template)

    return template.render(
        bot_running=bot_running,
        config=_dict_to_obj(config),
        status=_dict_to_obj(status) if status else None,
    )


@app.post("/start")
async def start_bot():
    """Запуск бота"""
    global bot_strategy, bot_running

    if not bot_running:
        try:
            bot_strategy = GridStrategy("config.json")
            bot_running = True
            print("🟢 Бот запущен")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка запуска: {str(e)}")

    return RedirectResponse(url="/", status_code=302)


@app.post("/stop")
async def stop_bot():
    """Остановка бота"""
    global bot_strategy, bot_running

    if bot_running:
        bot_running = False
        bot_strategy = None
        print("🔴 Бот остановлен")

    return RedirectResponse(url="/", status_code=302)


@app.post("/update_config")
async def update_config(
    symbol: str = Form(...),
    grid_mode: str = Form(...),
    step_percent: float = Form(...),
    tp_mode: str = Form(...),
    tp_percent: float = Form(...),
    levels_below: int = Form(...),
    quote_start: float = Form(...),
    compound: str = Form(None),
):
    """Обновление конфигурации"""

    # Загрузка текущей конфигурации
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    # Обновление параметров
    config["runtime"]["symbol"] = symbol
    config["grid"]["mode"] = grid_mode
    config["grid"]["step_percent"] = step_percent
    config["grid"]["tp_mode"] = tp_mode
    config["grid"]["tp_percent"] = tp_percent
    config["grid"]["levels_below"] = levels_below
    config["capital"]["quote_start"] = quote_start
    config["capital"]["compound"] = compound == "on"

    # Сохранение конфигурации
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print("⚙️ Конфигурация обновлена")
    return RedirectResponse(url="/", status_code=302)


@app.get("/api/status")
async def api_status():
    """API эндпоинт для получения статуса"""
    global bot_strategy, bot_running

    if bot_strategy:
        return {"running": bot_running, "status": bot_strategy.get_status()}
    else:
        return {"running": False, "status": None}


def _dict_to_obj(d):
    """Конвертация словаря в объект для удобного доступа в шаблонах"""
    if isinstance(d, dict):
        return type("obj", (object,), {k: _dict_to_obj(v) for k, v in d.items()})
    return d


if __name__ == "__main__":
    print("🚀 Запуск веб-интерфейса MEXC Grid Bot...")
    print("📱 Откройте http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
