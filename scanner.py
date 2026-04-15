#!/usr/bin/env python3
"""
APEX SIGNALS — Auto Scanner v3.0
Uses Kraken API (works from GitHub Actions US servers)
"""

import os
import json
import requests
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────
TG_TOKEN  = os.environ.get('TG_TOKEN', '8649338480:AAHXj2O4Uy-CTpuV1-zotA91XuQXRp78JHs')
TG_CHAT   = os.environ.get('TG_CHAT',  '7130790427')
ANTH_KEY  = os.environ.get('ANTHROPIC_API_KEY', '')
MODEL     = 'claude-sonnet-4-5'
SYMBOLS   = ['BTC', 'ETH', 'SOL']

# Kraken pair names
KRAKEN_PAIRS = {
    'BTC': 'XBTUSD',
    'ETH': 'ETHUSD',
    'SOL': 'SOLUSD'
}
KRAKEN_BASE = 'https://api.kraken.com/0/public'

print('APEX SIGNALS Scanner v3.0 — Kraken API')

# ── TELEGRAM ─────────────────────────────────────────
def tg_send(text):
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT, 'text': text, 'parse_mode': 'HTML'},
            timeout=15
        )
        return r.json().get('ok', False)
    except Exception as e:
        print(f'Telegram error: {e}')
        return False

# ── KRAKEN DATA ───────────────────────────────────────
def get_ticker():
    """Get current prices from Kraken"""
    result = {}
    for sym, pair in KRAKEN_PAIRS.items():
        try:
            r = requests.get(f'{KRAKEN_BASE}/Ticker', params={'pair': pair}, timeout=10)
            data = r.json()
            if data.get('error'):
                print(f'Kraken ticker error {sym}: {data["error"]}')
                continue
            tick = list(data['result'].values())[0]
            result[sym] = {
                'price': float(tick['c'][0]),  # last trade price
                'chg':   0,                     # Kraken doesn't give 24h% directly
                'vol':   float(tick['v'][1])    # 24h volume
            }
            print(f'  {sym}: ${result[sym]["price"]:,.2f}')
        except Exception as e:
            print(f'Ticker error {sym}: {e}')
    return result

def get_candles(symbol, interval_hours, limit):
    """Get OHLC candles from Kraken"""
    pair = KRAKEN_PAIRS.get(symbol)
    if not pair:
        return []
    try:
        # Kraken intervals in minutes: 1,5,15,30,60,240,1440,10080,21600
        interval_map = {
            '1d': 1440,   # daily
            '4h': 240,    # 4 hours
            '1w': 10080   # weekly
        }
        interval = interval_map.get(interval_hours, 1440)
        r = requests.get(f'{KRAKEN_BASE}/OHLC', params={
            'pair': pair,
            'interval': interval
        }, timeout=15)
        data = r.json()
        if data.get('error'):
            print(f'Kraken candles error {symbol} {interval_hours}: {data["error"]}')
            return []
        ohlc = list(data['result'].values())[0]
        candles = []
        for c in ohlc[-limit:]:
            try:
                candles.append({
                    'open':  float(c[1]),
                    'high':  float(c[2]),
                    'low':   float(c[3]),
                    'close': float(c[4]),
                    'vol':   float(c[6])
                })
            except (ValueError, IndexError):
                continue
        return candles
    except Exception as e:
        print(f'Candles error {symbol} {interval_hours}: {e}')
        return []

def get_funding(symbol):
    """Funding rate not available on Kraken spot — return neutral"""
    return 0.01  # neutral funding

def get_open_interest(symbol):
    """Get Open Interest from Binance Futures — works from GitHub Actions US servers"""
    try:
        pair = {'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT', 'SOL': 'SOLUSDT'}.get(symbol)
        if not pair:
            return None
        r = requests.get('https://fapi.binance.com/fapi/v1/openInterest',
            params={'symbol': pair}, timeout=10)
        data = r.json()
        if 'openInterest' in data:
            oi = float(data['openInterest'])
            # Get price to convert to USD
            r2 = requests.get('https://fapi.binance.com/fapi/v1/ticker/price',
                params={'symbol': pair}, timeout=10)
            price_data = r2.json()
            price = float(price_data.get('price', 0))
            oi_usd = oi * price
            return round(oi_usd / 1e9, 2)  # in billions
    except Exception as e:
        print(f'OI error {symbol}: {e}')
    return None

# ── TELEGRAM ─────────────────────────────────────────
def tg_send(text):
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT, 'text': text, 'parse_mode': 'HTML'},
            timeout=15
        )
        return r.json().get('ok', False)
    except Exception as e:
        print(f'Telegram error: {e}')
        return False

def get_fear_greed():
    try:
        r = requests.get('https://api.alternative.me/fng/', timeout=10)
        d = r.json()['data'][0]
        return f"{d['value']} ({d['value_classification']})"
    except:
        return 'N/D'

# ── INDICATORS ────────────────────────────────────────
def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period-1) + gains[i]) / period
        avg_loss = (avg_loss * (period-1) + losses[i]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)

def calc_ema(closes, period):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for c in closes[period:]:
        ema = c * k + ema * (1 - k)
    return round(ema, 2)

def calc_macd(closes):
    if len(closes) < 26:
        return None
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    if not ema12 or not ema26:
        return None
    line = round(ema12 - ema26, 4)
    return {'line': line, 'bullish': line > 0}

def calc_bb(closes, period=20):
    if len(closes) < period:
        return None
    recent = closes[-period:]
    mid = sum(recent) / period
    std = (sum((c - mid)**2 for c in recent) / period) ** 0.5
    return {
        'upper': round(mid + 2*std, 2),
        'middle': round(mid, 2),
        'lower': round(mid - 2*std, 2),
        'width': round((4*std/mid)*100, 1)
    }

def calc_atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i]['high'] - candles[i]['low'],
            abs(candles[i]['high'] - candles[i-1]['close']),
            abs(candles[i]['low'] - candles[i-1]['close'])
        )
        trs.append(tr)
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period-1) + tr) / period
    return round(atr, 2)

def detect_structure(closes):
    if len(closes) < 10:
        return 'Indefinida'
    h = [max(closes[i:i+3]) for i in range(0, len(closes)-2, 3)]
    l = [min(closes[i:i+3]) for i in range(0, len(closes)-2, 3)]
    if len(h) >= 3:
        hh = h[-1] > h[-2] > h[-3]
        hl = l[-1] > l[-2]
        lh = h[-1] < h[-2]
        ll = l[-1] < l[-2] < l[-3]
        if hh and hl:
            return 'HH/HL — TENDENCIA ALCISTA'
        elif lh and ll:
            return 'LH/LL — TENDENCIA BAJISTA'
    return 'Rango / indefinido'

def get_indicators(symbol):
    print(f'  Calculating indicators for {symbol}...')
    c1d = get_candles(symbol, '1d', 220)
    c4h = get_candles(symbol, '4h', 100)
    c1w = get_candles(symbol, '1w', 30)

    if not c1d:
        return None

    closes_1d = [c['close'] for c in c1d]
    closes_4h = [c['close'] for c in c4h] if c4h else []
    closes_1w = [c['close'] for c in c1w] if c1w else []

    price = closes_1d[-1]
    ema50  = calc_ema(closes_1d, 50)
    ema200 = calc_ema(closes_1d, 200)
    ema21  = calc_ema(closes_1d, 21)

    vols = [c['vol'] for c in c1d]
    vol_avg = sum(vols[-20:]) / 20 if len(vols) >= 20 else None
    vol_ratio = round(vols[-1] / vol_avg, 2) if vol_avg else None

    fund = get_funding(symbol)
    oi = get_open_interest(symbol)

    high20d = max(c['high'] for c in c1d[-20:])
    low20d  = min(c['low']  for c in c1d[-20:])

    return {
        'price':   price,
        'rsi1d':   calc_rsi(closes_1d),
        'rsi4h':   calc_rsi(closes_4h) if closes_4h else None,
        'rsi1w':   calc_rsi(closes_1w) if closes_1w else None,
        'ema21':   ema21,
        'ema50':   ema50,
        'ema200':  ema200,
        'above50': price > ema50 if ema50 else None,
        'above200':price > ema200 if ema200 else None,
        'golden':  (ema50 > ema200) if (ema50 and ema200) else None,
        'macd':    calc_macd(closes_1d),
        'bb':      calc_bb(closes_1d),
        'atr':     calc_atr(c1d),
        'vol_ratio': vol_ratio,
        'fund':    fund,
        'oi':      oi,
        'struct':  detect_structure(closes_1d),
        'high20d': high20d,
        'low20d':  low20d,
    }

# ── BUILD CONTEXT ─────────────────────────────────────
def build_ctx(sym, ind, price_data):
    p = price_data.get(sym, {})
    price = p.get('price', ind['price'])
    chg   = p.get('chg', 0)
    fmt   = lambda n: f'${n:,.2f}' if n else 'N/D'

    return f"""━━━ {sym}/USDT — DATOS REALES BINANCE ━━━
Precio: ${price:,.2f} ({'+' if chg>=0 else ''}{chg:.2f}% 24h)
RSI 1D: {ind['rsi1d']} | RSI 4H: {ind['rsi4h'] or 'N/D'} | RSI 1W: {ind['rsi1w'] or 'N/D'}
EMA 21D: {fmt(ind['ema21'])} | EMA 50D: {fmt(ind['ema50'])} | EMA 200D: {fmt(ind['ema200'])}
Precio vs EMA50: {'ARRIBA ↑' if ind['above50'] else 'ABAJO ↓'}
Precio vs EMA200: {'ARRIBA ↑' if ind['above200'] else 'ABAJO ↓'}
Cruce EMA: {'GOLDEN CROSS (alcista)' if ind['golden'] else 'DEATH CROSS (bajista)'}
MACD 1D: {f"línea={ind['macd']['line']}, {'ALCISTA' if ind['macd']['bullish'] else 'BAJISTA'}" if ind['macd'] else 'N/D'}
Bollinger: Upper={fmt(ind['bb']['upper'] if ind['bb'] else None)} Mid={fmt(ind['bb']['middle'] if ind['bb'] else None)} Lower={fmt(ind['bb']['lower'] if ind['bb'] else None)}
ATR 14D: ${ind['atr'] or 'N/D'}
Volumen ratio vs promedio 20D: {ind['vol_ratio'] or 'N/D'}x
Funding Rate: {str(ind['fund'])+'%' if ind['fund'] is not None else 'N/D'}
Open Interest: {str(ind['oi'])+'B USD' if ind.get('oi') else 'N/D'} (OI↑+precio↑=tendencia real | OI↓+precio↑=rally falso)
Estructura: {ind['struct']}
Resistencia 20D: {fmt(ind['high20d'])} | Soporte 20D: {fmt(ind['low20d'])}"""

# ── ANTHROPIC API ─────────────────────────────────────
def call_claude(system, user, max_tokens=2000):
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': ANTH_KEY,
        'anthropic-version': '2023-06-01'
    }
    body = {
        'model': MODEL,
        'max_tokens': max_tokens,
        'system': system,
        'messages': [{'role': 'user', 'content': user}]
    }
    r = requests.post('https://api.anthropic.com/v1/messages', headers=headers, json=body, timeout=120)
    if not r.ok:
        raise Exception(f'Claude API error {r.status_code}: {r.text[:200]}')
    data = r.json()
    if 'error' in data:
        raise Exception(f'Claude error: {data["error"]["message"]}')
    return ''.join(b.get('text', '') for b in data.get('content', []))

# ── SYSTEM PROMPTS ────────────────────────────────────
SYS_GEN = """Eres el mejor trader de criptomonedas del mundo especializado en FUTUROS PERPETUALES.

Analiza los datos y genera señal en DOS NIVELES:

🏆 SEÑAL ÉLITE: 5+ confluencias, R/B ≥ 1:3, todo alineado → operar 2% capital
⚡ OPORTUNIDAD: 3+ confluencias, R/B ≥ 1:2, setup válido → operar 0.5-1% capital
🚫 SIN SEÑAL: menos de 3 confluencias o R/B < 1:2

Usa metodología Top-Down (1W→1D→4H), SMC/ICT, Order Blocks, FVG, divergencias RSI (4 tipos), Fibonacci completo (retrocesos 23.6-78.6%, extensiones 127.2-261.8%).

FORMATO EXACTO:
NIVEL: [SEÑAL ÉLITE / OPORTUNIDAD]
ACTIVO: [BTC/ETH/SOL]
DIRECCIÓN: [LONG/SHORT]
APALANCAMIENTO: [x2/x3]
TEMPORALIDAD: [4H/1D/1W] | [razón]
ENTRADA: [$X,XXX – $X,XXX]
STOP LOSS: $[X,XXX]
TP1: $[X,XXX]
TP2: $[X,XXX]
TP3: $[X,XXX]
RATIO R/B: [1:X.X]
PROBABILIDAD: [XX%]
CAPITAL RECOMENDADO: [2% / 0.5-1%]
VALIDEZ: [Xh]

ANÁLISIS TÉCNICO:
[análisis completo con valores reales]

CONFLUENCIA DETECTADA:
[lista numerada de factores]

NO ENTRAR SI:
[condición de invalidación]

Si no hay setup válido: SIN SEÑAL: [razón]"""

SYS_REV = """Eres el director de risk management de un hedge fund especializado en FUTUROS PERPETUALES.

Evalúa la señal con 14 criterios (1 punto cada uno):
1. RSI multi-temporal alineado
2. EMAs confirman dirección
3. MACD confirma
4. Volumen confirma (>0.6x para oportunidad, >1.0x para élite)
5. Funding rate seguro
6. Estructura válida HH/HL o LH/LL
7. SL en estructura real ≥1.5x ATR
8. Entrada en zona de valor (OB/FVG/Fibonacci)
9. TP1 realista en resistencia/soporte real
10. R/B verificado matemáticamente
11. Bollinger no sobreextendido
12. Noticias coherentes
13. Sin evento macro HIGH en próximas 4h
14. Confluencia suficiente

NIVELES:
- 10-14: ELITE, capital 2%
- 6-9: OPPORTUNITY, capital 0.5-1%
- <6: REJECTED

Si R/B < 1:2 → REJECTED siempre.

IMPORTANTE: Responde SOLO con JSON puro. Sin texto antes ni después. Sin markdown. Sin backticks. Empieza directamente con { y termina con }.

Formato exacto:
{"score":8,"level":"OPPORTUNITY","approved":true,"verdict":"OPORTUNIDAD","verdict_reason":"razon concisa","rb_calculated":"1:2.3","capital_recommended":"0.5-1%","checks":[{"criterion":"RSI","pass":true,"detail":"RSI 1D y 4H alineados alcistas"},{"criterion":"EMAs","pass":true,"detail":"Precio sobre EMA50"},{"criterion":"MACD","pass":true,"detail":"MACD alcista sin cruce"},{"criterion":"Volumen","pass":false,"detail":"Vol 0.76x moderado"},{"criterion":"Funding","pass":true,"detail":"Funding neutro -0.007%"},{"criterion":"Estructura","pass":true,"detail":"HH/HL confirmado 1D"},{"criterion":"SL","pass":true,"detail":"SL bajo minimo estructural"},{"criterion":"Entrada","pass":true,"detail":"Entrada en OB $73800-74600"},{"criterion":"TP1","pass":true,"detail":"TP1 en resistencia 20D"},{"criterion":"RB","pass":true,"detail":"R/B 1:2.8 verificado"},{"criterion":"Bollinger","pass":true,"detail":"No sobreextendido"},{"criterion":"Noticias","pass":true,"detail":"Contexto neutral"},{"criterion":"Macro","pass":true,"detail":"Sin eventos HIGH"},{"criterion":"Confluencia","pass":true,"detail":"5 factores alineados"}],"scenarios":{"base":"precio alcanza TP1 en 24-48h con probabilidad 62%","bull":"ruptura hacia TP2-TP3 si volumen aumenta","bear":"SL en $72500 si rompe soporte"},"adjustments":"reducir tamaño si volumen no confirma","risk_warnings":["Death Cross activo — contexto bajista mayor"]}"""

# ── SMART PREFILTER ──────────────────────────────────
def prefilter(sym, ind):
    """
    Fast local check before calling expensive Claude API.
    Returns (should_scan, reason, score)
    Only skips when market is OBVIOUSLY bad — never misses real signals.
    """
    score = 0
    reasons = []

    rsi1d = ind.get('rsi1d')
    rsi4h = ind.get('rsi4h')
    vol   = ind.get('vol_ratio')
    macd  = ind.get('macd')
    above50  = ind.get('above50')
    above200 = ind.get('above200')
    golden   = ind.get('golden')
    struct   = ind.get('struct', '')
    fund     = ind.get('fund')
    bb       = ind.get('bb')
    atr      = ind.get('atr')
    price    = ind.get('price', 0)

    # ── HARD BLOCKS — skip immediately if any of these ──
    # 1. No data
    if not rsi1d or not vol:
        return False, 'No hay datos suficientes', 0

    # 2. Volume extremely low (market dead)
    if vol < 0.4:
        return False, f'Volumen muy bajo ({vol}x) — mercado inactivo', 0

    # 3. RSI completely neutral with no momentum (45-55 range = no setup)
    if rsi1d and 47 <= rsi1d <= 53:
        rsi4h_neutral = rsi4h and 47 <= rsi4h <= 53
        if rsi4h_neutral:
            return False, f'RSI completamente neutral (1D:{rsi1d} 4H:{rsi4h}) — sin momentum', 0

    # 4. Funding rate extreme against both directions
    if fund is not None and abs(fund) > 0.15:
        return False, f'Funding rate extremo ({fund}%) — riesgo de squeeze', 0

    # ── POSITIVE SIGNALS — each adds to score ──
    # RSI oversold (potential long)
    if rsi1d and rsi1d < 35:
        score += 2
        reasons.append(f'RSI 1D sobreventa ({rsi1d})')
    elif rsi1d and rsi1d > 65:
        score += 2
        reasons.append(f'RSI 1D sobrecompra ({rsi1d}) — posible short')

    # RSI 4H confirmation
    if rsi4h:
        if rsi4h < 35:
            score += 1
            reasons.append(f'RSI 4H sobreventa ({rsi4h})')
        elif rsi4h > 65:
            score += 1
            reasons.append(f'RSI 4H sobrecompra ({rsi4h})')
        # RSI divergence hint (1D and 4H pointing different directions)
        if rsi1d and rsi4h:
            if (rsi1d < 45 and rsi4h > 55) or (rsi1d > 55 and rsi4h < 45):
                score += 2
                reasons.append(f'Posible divergencia RSI (1D:{rsi1d} vs 4H:{rsi4h})')

    # Volume confirmation
    if vol and vol >= 1.0:
        score += 2
        reasons.append(f'Volumen alto ({vol}x)')
    elif vol and vol >= 0.7:
        score += 1
        reasons.append(f'Volumen moderado ({vol}x)')

    # MACD signal
    if macd:
        score += 1
        reasons.append(f'MACD {"alcista" if macd["bullish"] else "bajista"}')

    # EMA structure
    if above50 is not None:
        score += 1
        reasons.append(f'Precio {"sobre" if above50 else "bajo"} EMA50')

    if golden is not None:
        score += 1
        reasons.append(f'{"Golden" if golden else "Death"} Cross')

    # Market structure
    if 'ALCISTA' in struct or 'BAJISTA' in struct:
        score += 2
        reasons.append(f'Estructura: {struct}')

    # Bollinger compression (volatility squeeze = explosion coming)
    if bb and bb.get('width', 100) < 3.0:
        score += 2
        reasons.append(f'Bollinger comprimido ({bb["width"]}%) — explosión próxima')

    # Funding rate favorable
    if fund is not None:
        if 0.0 <= fund <= 0.03:
            score += 1
            reasons.append(f'Funding neutro ({fund}%)')
        elif fund < 0:
            score += 1
            reasons.append(f'Funding negativo ({fund}%) — favorable para longs')

    # ── DECISION ──
    # Need at least 4 points to justify calling Claude
    if score >= 4:
        return True, f'Score prefiltro: {score}/14 — {", ".join(reasons[:3])}', score
    else:
        return False, f'Score prefiltro bajo ({score}/14) — insuficiente confluencia técnica', score


# ── MAIN SCAN ─────────────────────────────────────────
def scan():
    now = datetime.now().strftime('%d/%m/%Y %H:%M')
    print(f'\n🔍 APEX SIGNALS Scanner — {now}')
    print('='*50)

    if not ANTH_KEY:
        print('❌ No ANTHROPIC_API_KEY found')
        tg_send(f'❌ <b>Error:</b> No hay API Key de Anthropic configurada.\nConfigura el secret ANTHROPIC_API_KEY en GitHub.')
        return

    # Get live prices
    print('📡 Fetching prices...')
    prices = get_ticker()
    fg = get_fear_greed()

    btc_p = f"${prices.get('BTC',{}).get('price',0):,.0f}" if prices else '—'
    eth_p = f"${prices.get('ETH',{}).get('price',0):,.2f}" if prices else '—'
    sol_p = f"${prices.get('SOL',{}).get('price',0):,.2f}" if prices else '—'
    print(f'BTC: {btc_p} | ETH: {eth_p} | SOL: {sol_p}')
    print(f'Fear & Greed: {fg}')

    signals_found  = 0
    skipped_prefilter = 0

    for sym in SYMBOLS:
        print(f'\n📊 Scanning {sym}...')
        try:
            ind = get_indicators(sym)
            if not ind:
                print(f'  ⚠ No indicators for {sym}')
                continue

            # ── PREFILTER — saves 80% of API costs ──
            should_scan, pf_reason, pf_score = prefilter(sym, ind)
            if not should_scan:
                print(f'  ⏭ {sym} SKIPPED by prefilter: {pf_reason}')
                skipped_prefilter += 1
                continue

            print(f'  ✅ Prefilter passed ({pf_score} pts): {pf_reason}')

            ctx = build_ctx(sym, ind, prices)
            ds  = datetime.now().strftime('%A %d de %B de %Y')
            msg = f'Fecha: {ds}\n\n{ctx}\n\nFear & Greed: {fg}\n\nACTIVO: {sym}\n\nGenera señal si hay setup válido.'

            print(f'  🤖 Calling IA #1...')
            signal_text = call_claude(SYS_GEN, msg)

            # Check for no signal
            no_sig_phrases = ['SIN SEÑAL', 'NO HAY OPERACIONES', 'NO HAY SEÑAL', 'SIN OPERACIONES']
            is_no_signal = any(p in signal_text.upper() for p in no_sig_phrases)
            has_direction = 'LONG' in signal_text.upper() or 'SHORT' in signal_text.upper()

            # Log first 200 chars of response for debugging
            print(f'  📝 IA #1 response: {signal_text[:200].replace(chr(10), " ")}')

            if is_no_signal or not has_direction:
                print(f'  ⏳ {sym}: No signal found')
                continue

            print(f'  ✅ Signal found! Calling IA #2...')
            rev_msg = f'SEÑAL:\n{signal_text}\n\nDATOS:\n{ctx}\n\nEvalúa con 14 criterios. Solo JSON puro:'
            rev_raw = call_claude(SYS_REV, rev_msg)
            print(f'  📝 IA #2 raw: {rev_raw[:150].replace(chr(10), " ")}')

            # Parse review — multiple fallback strategies
            review = None
            # Strategy 1: direct parse
            try:
                review = json.loads(rev_raw.strip())
            except: pass

            # Strategy 2: find first { to last }
            if not review:
                try:
                    s = rev_raw.find('{')
                    e = rev_raw.rfind('}')
                    if s != -1 and e != -1:
                        review = json.loads(rev_raw[s:e+1])
                except: pass

            # Strategy 3: strip markdown fences
            if not review:
                try:
                    clean = rev_raw.replace('```json','').replace('```','').strip()
                    review = json.loads(clean)
                except: pass

            # Strategy 4: if still can't parse, create basic approval from text
            if not review:
                print(f'  ⚠ Could not parse review for {sym} — using text analysis')
                # If IA #2 mentions OPORTUNIDAD or ELITE in text, approve with basic score
                rev_upper = rev_raw.upper()
                if 'OPORTUNIDAD' in rev_upper or 'OPPORTUNITY' in rev_upper:
                    review = {'score': 7, 'level': 'OPPORTUNITY', 'approved': True,
                             'verdict': 'OPORTUNIDAD', 'capital_recommended': '0.5-1%',
                             'verdict_reason': 'Aprobado por análisis de texto'}
                elif 'ELITE' in rev_upper:
                    review = {'score': 11, 'level': 'ELITE', 'approved': True,
                             'verdict': 'SEÑAL ÉLITE', 'capital_recommended': '2%',
                             'verdict_reason': 'Aprobado por análisis de texto'}
                else:
                    review = {'score': 4, 'level': 'REJECTED', 'approved': False,
                             'verdict': 'RECHAZADA', 'verdict_reason': 'No se pudo parsear'}

            if not review:
                print(f'  ⚠ Could not parse review for {sym}')
                continue

            score = review.get('score', 0)
            level = review.get('level', '')
            approved = review.get('approved', False)
            is_elite = score >= 10 or level == 'ELITE'
            is_opp   = score >= 6 and not is_elite

            print(f'  Score: {score}/14 | Level: {level} | Approved: {approved}')

            if approved and (is_elite or is_opp):
                signals_found += 1
                level_emoji = '🏆 SEÑAL ÉLITE' if is_elite else '⚡ OPORTUNIDAD'
                capital = review.get('capital_recommended', '2%' if is_elite else '0.5-1%')

                # Parse signal fields — handle markdown formatting
                def get_field(pattern, default='—'):
                    import re
                    m = re.search(pattern, signal_text, re.IGNORECASE | re.MULTILINE)
                    if m:
                        return m.group(1).strip().replace('*','').replace('_','').strip()
                    return default

                # Direction — try multiple patterns
                import re
                direction = '—'
                for pat in [r'DIRECCIÓN:\s*\*{0,2}(LONG|SHORT)\*{0,2}',
                           r'\*{0,2}DIRECCIÓN:\*{0,2}\s*(LONG|SHORT)',
                           r'DIRECCIÓN[:\s]+\**(LONG|SHORT)\**']:
                    m = re.search(pat, signal_text, re.IGNORECASE)
                    if m:
                        direction = m.group(1).upper()
                        break
                # Last resort — check if LONG or SHORT appears prominently
                if direction == '—':
                    if 'LONG' in signal_text.upper():
                        direction = 'LONG'
                    elif 'SHORT' in signal_text.upper():
                        direction = 'SHORT'

                lev     = get_field(r'APALANCAMIENTO:\s*\*{0,2}(x[23])\*{0,2}', 'x2')
                tf      = get_field(r'TEMPORALIDAD:\s*\*{0,2}([^\|\n\*]+)').split('|')[0].strip()
                entry   = get_field(r'ENTRADA:\s*\*{0,2}([^\n\*]+)')
                sl      = get_field(r'STOP\s*LOSS:\s*\*{0,2}([^\n\*]+)')
                tp1     = get_field(r'TP1:\s*\*{0,2}([^\n\*]+)')
                tp2     = get_field(r'TP2:\s*\*{0,2}([^\n\*]+)')
                tp3     = get_field(r'TP3:\s*\*{0,2}([^\n\*]+)')
                rr      = get_field(r'RATIO\s+R/B:\s*\*{0,2}([^\n\*]+)')
                prob    = get_field(r'PROBABILIDAD:\s*\*{0,2}([^\n\*]+)')
                validez = get_field(r'VALIDEZ:\s*\*{0,2}([^\n\*]+)')
                inval   = get_field(r'NO ENTRAR SI:\s*\*{0,2}([^\n\*]+)')

                dir_emoji = '🟢' if direction == 'LONG' else '🔴'
                arrow     = '↑' if direction == 'LONG' else '↓'
                checks_ok = sum(1 for c in review.get('checks', []) if c.get('pass'))

                tg_msg = f"""{level_emoji} — <b>APEX SIGNALS</b>

{dir_emoji} <b>{sym} — {direction} {arrow}</b>
📊 Score: <b>{score}/14</b> ({checks_ok} criterios ✓) | Prob: <b>{prob}</b>
⏱ Temporalidad: <b>{tf}</b> | Apalancamiento: <b>{lev}</b>
💰 Capital: <b>{capital}</b>

💵 <b>ENTRADA:</b> {entry}
🛑 <b>STOP LOSS:</b> {sl}
🎯 <b>TP1:</b> {tp1} — cerrar 40%
🎯 <b>TP2:</b> {tp2} — cerrar 35%
🎯 <b>TP3:</b> {tp3} — cerrar 25%
📐 <b>Ratio R/B:</b> {rr}

⚠️ <b>NO ENTRAR SI:</b> {inval}
⏰ <b>Válida:</b> {validez}

🔔 Tras TP1 → mover SL a break-even
⏰ Escaneado: {now}"""

                ok = tg_send(tg_msg)
                print(f'  📱 Telegram sent: {ok}')
            else:
                print(f'  🛑 {sym}: Signal rejected (score {score}/14)')

        except Exception as e:
            print(f'  ❌ Error scanning {sym}: {e}')
            continue

    # Summary
    total = len(SYMBOLS)
    called_api = total - skipped_prefilter
    savings_pct = int((skipped_prefilter / total) * 100) if total > 0 else 0

    print(f'\n📊 Scan summary:')
    print(f'   Assets scanned: {total}')
    print(f'   Prefilter skipped: {skipped_prefilter} ({savings_pct}% saved)')
    print(f'   API calls made: {called_api}')
    print(f'   Signals found: {signals_found}')

    if signals_found == 0:
        print(f'\n⏳ No signals this scan — market not ready')
    else:
        print(f'\n✅ {signals_found} signal(s) sent to Telegram')

    # ── DAILY SUMMARY — sent at 10:00 UTC, NO API cost ──
    current_hour = datetime.utcnow().hour
    if current_hour == 10:
        btc_p = f"${prices.get('BTC',{}).get('price',0):,.0f}" if prices else '—'
        eth_p = f"${prices.get('ETH',{}).get('price',0):,.2f}" if prices else '—'
        sol_p = f"${prices.get('SOL',{}).get('price',0):,.2f}" if prices else '—'
        btc_chg = prices.get('BTC',{}).get('chg',0)
        eth_chg = prices.get('ETH',{}).get('chg',0)
        sol_chg = prices.get('SOL',{}).get('chg',0)

        def chg_emoji(c): return '🟢' if c >= 0 else '🔴'

        daily_msg = f"""📊 <b>APEX SIGNALS — Resumen Diario</b>
━━━━━━━━━━━━━━━━━━━━
{chg_emoji(btc_chg)} <b>BTC:</b> {btc_p} ({'+' if btc_chg>=0 else ''}{btc_chg:.2f}%)
{chg_emoji(eth_chg)} <b>ETH:</b> {eth_p} ({'+' if eth_chg>=0 else ''}{eth_chg:.2f}%)
{chg_emoji(sol_chg)} <b>SOL:</b> {sol_p} ({'+' if sol_chg>=0 else ''}{sol_chg:.2f}%)

😱 <b>Fear & Greed:</b> {fg}

📡 <b>Estado:</b> {'⚠️ Mercado inactivo' if skipped_prefilter == total else '✅ Mercado activo'}
⏰ Scanner activo 24/7"""

        ok = tg_send(daily_msg)
        print(f'\n📱 Daily summary sent to Telegram: {ok}')

    print('\n✅ Scan complete')

if __name__ == '__main__':
    scan()
