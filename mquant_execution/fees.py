from .money import dec, money

def calculate_fee(gross, asset_type, side, config):
    gross=dec(gross); commission=max(money(gross*config.commission_rate), money(config.min_commission)) if gross else dec(0)
    stamp=money(gross*(config.stock_stamp_tax if asset_type=='stock' and side=='SELL' else config.etf_stamp_tax if side=='SELL' else 0))
    return money(commission+stamp), money(commission), money(stamp)
