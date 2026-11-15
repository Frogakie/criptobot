# criptobot

Bot de trading para Binance que usa un cruce de medias móviles simples (SMA).
Puedes cambiar su configuración **mientras corre**: edita y guarda `config.json`
y el bot aplica los cambios en el siguiente ciclo, sin reiniciarse.

> ⚠️ **Advertencia:** el trading de criptomonedas es de alto riesgo. Este software
> se entrega tal cual, sin garantías. Prueba siempre en `paper` o `testnet` antes
> de usar `live`.

## Estructura

```
criptobot/
├── bot.py                  # Punto de entrada (python bot.py / PyInstaller)
├── config.example.json     # Plantilla de configuración (copiar a config.json)
├── requirements.txt        # Dependencias
├── criptobot/              # Código del bot
│   ├── __main__.py         # Permite: python -m criptobot
│   ├── runner.py           # Bucle principal (clase Bot)
│   ├── config.py           # Lectura de config.json con hot-reload
│   ├── client.py           # Cliente REST de Binance (firmas, hora del servidor, órdenes)
│   ├── rules.py            # Reglas de cada par (LOT_SIZE, NOTIONAL) y ajuste de cantidades
│   ├── state.py            # Posición abierta guardada en disco (state_<modo>.json)
│   ├── strategy.py         # Estrategia SMA crossover
│   ├── backtest.py         # Backtester (python -m criptobot.backtest)
│   ├── data.py             # Descarga de velas históricas con caché en data/
│   ├── logging_setup.py    # Log a bot.log y consola
│   └── paths.py            # Rutas de config.json / bot.log
└── tests/                  # Tests unitarios (unittest)
```

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate        # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.json config.json
```

`config.json` está en `.gitignore`, así que tus claves de API no se suben al repositorio.
Si arrancas el bot sin `config.json`, lo crea a partir de la plantilla y se detiene
para que lo revises.

## Uso

```bash
python bot.py
# o
python -m criptobot
```

El log se escribe en la consola y en `bot.log`.

### Cómo decide y opera el bot

- **Solo usa velas cerradas.** La señal se calcula al cerrar cada vela y cada vela se
  evalúa una sola vez, así que la señal no cambia a mitad de vela.
- **Respeta las reglas del par.** Antes de enviar una orden ajusta la cantidad al
  `stepSize` y comprueba el mínimo y el valor mínimo de la orden. Si no cumple, no la envía
  y lo indica en el log.
- **Recuerda su posición.** La guarda en `state_paper.json`, `state_testnet.json` o
  `state_live.json` (un archivo por modo). En testnet y live la compara al arrancar con tu
  saldo real y la corrige si no coincide. **Solo vende lo que compró él**: las monedas que ya
  tuvieras en la cuenta no se tocan.
- **Se sincroniza con la hora de Binance**, así un reloj desajustado no provoca rechazos.
- **Descuenta la comisión.** Al comprar, Binance cobra la comisión en la moneda comprada; el
  bot guarda la cantidad neta para poder venderla entera después.
- **Si se corta la conexión al enviar una orden**, busca la orden por su ID antes de darla
  por fallida.
- Al cerrar cada posición registra la ganancia o pérdida y el acumulado.

## Configuración (`config.json`)

| Clave            | Descripción                                                        |
|------------------|--------------------------------------------------------------------|
| `mode`           | `paper` (simulado con precios reales), `testnet` o `live` (dinero real) |
| `enabled`        | `false` pausa el bot sin cerrarlo                                  |
| `api_key`, `api_secret` | Solo necesarias en `testnet` / `live`                       |
| `symbol`         | Par a operar, p. ej. `BTCUSDT`                                     |
| `interval`       | Intervalo de las velas, p. ej. `1m`, `5m`, `1h`                    |
| `order_quantity` | Cantidad por orden                                                 |
| `poll_seconds`   | Segundos entre ciclos                                              |
| `sma_fast`, `sma_slow` | Periodos de las medias rápida y lenta                        |
| `fee_rate`       | Comisión por operación (0.001 = 0.1 %). Se usa en paper y en el backtester |

Las claves que empiezan por `_` son solo comentarios.

## Backtester

Simula la estrategia con datos históricos de Binance antes de arriesgar dinero:

```bash
python -m criptobot.backtest --symbol BTCUSDT --interval 1h --start 2024-01-01
python -m criptobot.backtest --interval 4h --start 2023-01-01 --end 2025-01-01 \
    --fast 20 --slow 50 --trades-out operaciones.csv
python -m criptobot.backtest --help
```

- Los valores que no indiques (par, intervalo, medias, comisión) se toman de `config.json`.
- Las velas descargadas se guardan en `data/`; la siguiente vez se usan sin volver a descargar.
- La orden se simula a la **apertura de la vela siguiente** a la señal, con comisión
  (`--fee`, 0.1 % por defecto) y deslizamiento (`--slippage`, 0.05 % por defecto).
- El informe muestra rentabilidad, comparación con comprar y mantener, caída máxima,
  % de operaciones ganadoras, profit factor, comisiones pagadas y tiempo en mercado.
- `--csv archivo.csv` usa velas propias (columnas `open_time,open,high,low,close,volume,close_time`).

> Con menos de ~30 operaciones el resultado no es fiable. Y que una estrategia haya ganado
> en el pasado no garantiza que gane en el futuro.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Empaquetar como .exe (opcional)

```bash
pip install pyinstaller
pyinstaller --onefile bot.py
```

Coloca `config.json` (o `config.example.json`) junto al `.exe` generado en `dist/`.
