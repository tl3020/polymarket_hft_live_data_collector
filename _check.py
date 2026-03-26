import json
f = '/usr/local/application/polymarket-hft-live-data-collector/data/btc_1h/2026-03-26/bitcoin-up-or-down-march-26-2026-4am-et.jsonl'
types = {}
pc_sample = None
for line in open(f):
    d = json.loads(line)
    et = d.get('event_type','unknown')
    types[et] = types.get(et, 0) + 1
    if et == 'price_change' and pc_sample is None:
        pc_sample = d
print('Event counts:', types)
print()
if pc_sample:
    pc_sample.pop('local_ts', None)
    print('price_change sample:')
    print(json.dumps(pc_sample, indent=2)[:800])
