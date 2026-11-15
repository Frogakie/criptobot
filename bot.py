#!/usr/bin/env python3
"""
Punto de entrada del bot de trading para Binance.

Uso:  python bot.py      (o:  python -m criptobot)

El código vive en el paquete `criptobot/`. Este archivo se mantiene en la raíz
para poder ejecutarlo directamente y para empaquetarlo con PyInstaller.

ADVERTENCIA: El trading de criptomonedas es de alto riesgo. Este software se
entrega tal cual, sin garantías. Prueba SIEMPRE en paper/testnet primero.
"""

from criptobot.runner import main

if __name__ == "__main__":
    main()
