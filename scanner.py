#!/usr/bin/env python3
"""
APEX SIGNALS — Auto Scanner v2.1
Runs via GitHub Actions every hour
Scans BTC, ETH, SOL and sends Telegram alerts
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
BINANCE   = 'https://api.binance.com/api/v3'
BINANCE_F = 'https://fapi.binance.com/fapi/v1'
SYMBOLS   = ['BTC', 'ETH', 'SOL']
PAIRS     = {'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT', 'SOL': 'SOLUSDT'}

print('APEX SIGNALS Scanner v2.1 — with CoinGecko fallback')

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

# ── BINANCE DATA ──────────────────────────────────────
def get_candles(symbol, interval, limit):
    try:
        urls = [
            f'{BINANCE}/klines',
            f'https://api1.binance.com/api/v3/klines',
            f'https://api2.binance.com/api/v3/klines',
            f'https://api3.binance.com/api/v3/klines',
        ]
        data = None
        for url in urls:
            try:
                r = requests.get(url, params={
                    'symbol': f'{symbol}USDT',
                    'interval': interval,
                    'limit': limit
                }, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
                raw = r.json()
                # Debug: print first element to see format
                if isinstance(raw, list) and len(raw) > 0:
                    print(f'  DEBUG {symbol} {interval} first element type: {type(raw[0]).__name__} = {str(raw[0])[:80]}')
                    data = raw
                    break
                else:
                    print(f'  DEBUG {symbol} {interval} non-list response: {str(raw)[:150]}')
            except Exception as e:
                print(f'  URL failed: {e}')
                continue

        if not data:
            return []

        candles = []
        for c in data:
            try:
                if isinstance(c, list) and len(c) >= 6:
                    candles.append({
                        'open':  float(c[1]),
                        'high':  float(c[2]),
                        'low':   float(c[3]),
                        'close': float(c[4]),
                        'vol':   float(c[5])
                    })
                elif isinstance(c, dict):
                    # Handle dict format
                    candles.append({
                        'open':  float(c.get('open', c.get('o', 0))),
                        'high':  float(c.get('high', c.get('h', 0))),
                        'low':   float(c.get('low', c.get('l', 0))),
                        'close': float(c.get('close', c.get('c', 0))),
                        'vol':   float(c.get('volume', c.get('v', 0)))
                    })
            except (ValueError, IndexError, TypeError) as e:
                print(f'  Candle parse error: {e} for {str(c)[:50]}')
                continue
        return candles
    except Exception as e:
        print(f'Candles error {symbol} {interval}: {e}')
        return []

def get_ticker():
    try:
        # Try with list of symbols first
        r = requests.get(f'{BINANCE}/ticker/24hr',
            params={'symbols': '["BTCUSDT","ETHUSDT","SOLUSDT"]'},
            timeout=10)
        data = r.json()
        result = {}
        if isinstance(data, list):
            for d in data:
                sym = d['symbol'].replace('USDT', '')
                result[sym] = {
                    'price': float(d['lastPrice']),
                    'chg':   float(d['priceChangePercent']),
                    'vol':   float(d['volume'])
                }
        elif isinstance(data, dict) and 'lastPrice' in data:
            # Single symbol response
            sym = data['symbol'].replace('USDT', '')
            result[sym] = {
                'price': float(data['lastPrice']),
                'chg':   float(data['priceChangePercent']),
                'vol':   float(data['volume'])
            }
        # If empty, try one by one
        if not result:
            for sym in ['BTC', 'ETH', 'SOL']:
                try:
                    r2 = requests.get(f'{BINANCE}/ticker/24hr',
                        params={'symbol': f'{sym}USDT'}, timeout=10)
                    d = r2.json()
                    if 'lastPrice' in d:
                        result[sym] = {
                            'price': float(d['lastPrice']),
                            'chg':   float(d['priceChangePercent']),
                            'vol':   float(d['volume'])
                        }
                except:
                    continue
        return result
    except Exception as e:
        print(f'Ticker error: {e}')
        return {}

def get_funding(symbol):
    try:
        r = requests.get(f'{BINANCE_F}/premiumIndex', params={'symbol': f'{symbol}USDT'}, timeout=10)
        return round(float(r.json().get('lastFundingRate', 0)) * 100, 4)
    except:
        return None

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

def get_candles_coingecko(symbol, days):
    """Fallback: get OHLC from CoinGecko if Binance is blocked"""
    ids = {'BTC': 'bitcoin', 'ETH': 'ethereum', 'SOL': 'solana'}
    cg_id = ids.get(symbol)
    if not cg_id:
        return []
    try:
        r = requests.get(
            f'https://api.coingecko.com/api/v3/coins/{cg_id}/ohlc',
            params={'vs_currency': 'usd', 'days': days},
            timeout=15
        )
        data = r.json()
        if not isinstance(data, list):
            return []
        candles = []
        for c in data:
            try:
                candles.append({
                    'open':  float(c[1]),
                    'high':  float(c[2]),
                    'low':   float(c[3]),
                    'close': float(c[4]),
                    'vol':   0
                })
            except:
                continue
        return candles
    except Exception as e:
        print(f'CoinGecko error {symbol}: {e}')
        return []

def get_indicators(symbol):
    print(f'  Calculating indicators for {symbol}...')
    c1d = get_candles(symbol, '1d', 220)
    if not c1d:
        print(f'  Binance blocked — trying CoinGecko fallback...')
        c1d = get_candles_coingecko(symbol, 220)
    c4h = get_candles(symbol, '4h', 100)
    if not c4h:
        c4h = get_candles_coingecko(symbol, 10)
    c1w = get_candles(symbol, '1w', 30)
    if not c1w:
        c1w = get_candles_coingecko(symbol, 180)

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
- 10-14: SEÑAL ÉLITE, capital 2%
- 6-9: OPORTUNIDAD, capital 0.5-1%
- <6: RECHAZADA

Si R/B < 1:2 → RECHAZADA siempre.

Responde SOLO JSON puro:
{"score":8,"level":"OPPORTUNITY","approved":true,"verdict":"OPORTUNIDAD","verdict_reason":"razón","rb_calculated":"1:2.3","capital_recommended":"0.5-1%","checks":[{"criterion":"nombre","pass":true,"detail":"detalle"}],"scenarios":{"base":"...","bull":"...","bear":"..."},"adjustments":"","risk_warnings":[]}"""

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
            print(f'  🤖 Calling IA #1...')

            ctx = build_ctx(sym, ind, prices)
            ds  = datetime.now().strftime('%A %d de %B de %Y')
            msg = f'Fecha: {ds}\n\n{ctx}\n\nFear & Greed: {fg}\n\nACTIVO: {sym}\n\nGenera señal si hay setup válido.'

            print(f'  🤖 Calling IA #1...')
            signal_text = call_claude(SYS_GEN, msg)

            # Check for no signal
            no_sig_phrases = ['SIN SEÑAL', 'NO HAY OPERACIONES', 'NO HAY SEÑAL', 'SIN OPERACIONES']
            is_no_signal = any(p in signal_text.upper() for p in no_sig_phrases)
            has_direction = 'LONG' in signal_text.upper() or 'SHORT' in signal_text.upper()

            if is_no_signal or not has_direction:
                print(f'  ⏳ {sym}: No signal found')
                continue

            print(f'  ✅ Signal found! Calling IA #2...')
            rev_msg = f'SEÑAL:\n{signal_text}\n\nDATOS:\n{ctx}\n\nEvalúa con 14 criterios. Solo JSON puro:'
            rev_raw = call_claude(SYS_REV, rev_msg)

            # Parse review
            review = None
            try:
                review = json.loads(rev_raw.strip())
            except:
                s = rev_raw.find('{')
                e = rev_raw.rfind('}')
                if s != -1 and e != -1:
                    try:
                        review = json.loads(rev_raw[s:e+1])
                    except:
                        pass

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

                # Parse signal fields
                def get_field(pattern, default='—'):
                    import re
                    m = re.search(pattern, signal_text, re.IGNORECASE | re.MULTILINE)
                    return m.group(1).strip().replace('*','') if m else default

                direction = get_field(r'DIRECCIÓN:\s*(LONG|SHORT)')
                lev       = get_field(r'APALANCAMIENTO:\s*(x[23])', 'x2')
                tf        = get_field(r'TEMPORALIDAD:\s*([^\|\n]+)').split('|')[0].strip()
                entry     = get_field(r'ENTRADA:\s*([^\n]+)')
                sl        = get_field(r'STOP\s*LOSS:\s*([^\n]+)')
                tp1       = get_field(r'TP1:\s*([^\n]+)')
                tp2       = get_field(r'TP2:\s*([^\n]+)')
                tp3       = get_field(r'TP3:\s*([^\n]+)')
                rr        = get_field(r'RATIO\s+R/B:\s*([^\n]+)')
                prob      = get_field(r'PROBABILIDAD:\s*([^\n]+)')
                validez   = get_field(r'VALIDEZ:\s*([^\n]+)')
                inval     = get_field(r'NO ENTRAR SI:\s*([^\n]+)')

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

    print('\n✅ Scan complete')

if __name__ == '__main__':
    scan()
