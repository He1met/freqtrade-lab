"""Decode only bound spot bytes; daily history appears only after full UTC close."""
import json
from decimal import Decimal as D
from lab.spot139_model import Rule
from lab.spot139_binding import validate_sources,BindingError


def decode(manifest):
    validate_sources(manifest)
    hourly={};daily={};markets=[];rules={}
    metadata=json.load(open(manifest['sources'][0]['path']))
    for m in metadata['symbols']:
        s=m['baseAsset']+'/USDT';filters={f['filterType']:f for f in m['filters']}
        lot=filters['LOT_SIZE'];marketlot=filters['MARKET_LOT_SIZE'];price=filters['PRICE_FILTER']
        step=max(D(lot['stepSize']),D(marketlot['stepSize']))
        minq=max(D(lot['minQty']),D(marketlot['minQty']));maxq=min(D(lot['maxQty']),D(marketlot['maxQty']))
        mincost=D(filters['NOTIONAL']['minNotional'])
        rules[s]=Rule(step,minq,mincost,maxq,D(10)**-m['baseCommissionPrecision'],D(10)**-m['quoteCommissionPrecision'],D(price['tickSize']))
        markets.append(dict(id=m['symbol'],symbol=s,base=m['baseAsset'],quote='USDT',baseId=m['baseAsset'],quoteId='USDT',active=True,spot=True,contract=False,swap=False,future=False,option=False,type='spot',contractSize=1.,precision={'amount':float(step),'price':float(price['tickSize'])},limits={'amount':{'min':float(minq),'max':float(maxq)},'price':{'min':float(price['minPrice']),'max':float(price['maxPrice'])},'cost':{'min':float(mincost),'max':float(filters['NOTIONAL']['maxNotional'])},'leverage':{'min':1,'max':1}},maker=.001,taker=.001,info={}))
        hourly[s]={};daily[s]={}
    for source in manifest['sources'][1:]:
        request=source['request'];s=request['symbol'][:-4]+'/USDT';interval=request['interval']
        for bar in json.load(open(source['path'])):
            hour=bar[0]//3600000;ohlc=tuple(D(x) for x in bar[1:5])
            if interval=='1d':daily[s][hour//24]=ohlc
            elif interval=='1h':
                if hour in hourly[s]:raise BindingError('duplicate hour')
                hourly[s][hour]=(ohlc,bar[6]==bar[0]+3599999)
            else:raise BindingError('unbound interval')
    return hourly,daily,markets,rules


def history_at(hour,hourly,daily):
    # Called at midnight: only the immediately completed full day can be added.
    if hour%24==0:
        for s,bars in hourly.items():
            xs=[bars.get(h) for h in range(hour-24,hour)]
            if all(x is not None and x[1] for x in xs):
                daily[s][hour//24-1]=(xs[0][0][0],max(x[0][1] for x in xs),min(x[0][2] for x in xs),xs[-1][0][3])
    return {s:{d:b for d,b in days.items() if d<hour//24} for s,days in daily.items()}
