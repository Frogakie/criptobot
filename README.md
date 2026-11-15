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
│   ├── runner.py           # Bucle principal
│   ├── config.py           # Lectura de config.json con hot-reload
│   ├── client.py           # Cliente REST de Binance (firmado HMAC-SHA256)
│   ├── strategy.py         # Estrategia SMA crossover
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

Las claves que empiezan por `_` son solo comentarios.

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
