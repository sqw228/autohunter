import asyncpg

from sources import CarListing


CREATE_SQL = '''
CREATE TABLE IF NOT EXISTS listings (
 id BIGSERIAL PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL, url TEXT NOT NULL,
 brand TEXT, model TEXT, brand_id INTEGER, model_id INTEGER, generation TEXT, year INTEGER,
 mileage_km INTEGER, price_usd DOUBLE PRECISION, city TEXT, seller_type TEXT, title TEXT,
 description TEXT, published_at TIMESTAMPTZ, first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), notified BOOLEAN NOT NULL DEFAULT FALSE,
 UNIQUE(source, source_id)
);
CREATE TABLE IF NOT EXISTS subscribers (chat_id BIGINT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE IF NOT EXISTS market_cache (cache_key TEXT PRIMARY KEY, median_usd DOUBLE PRECISION,
 cached_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
'''

class Database:
 def __init__(self, url: str): self.url=url; self.pool=None
 async def connect(self):
  self.pool=await asyncpg.create_pool(self.url,min_size=1,max_size=5)
  async with self.pool.acquire() as c: await c.execute(CREATE_SQL)
 async def close(self):
  if self.pool: await self.pool.close()
 async def add_subscriber(self,chat_id:int):
  async with self.pool.acquire() as c: await c.execute('INSERT INTO subscribers(chat_id) VALUES($1) ON CONFLICT(chat_id) DO NOTHING',chat_id)
 async def subscribers(self):
  async with self.pool.acquire() as c: return [int(r['chat_id']) for r in await c.fetch('SELECT chat_id FROM subscribers')]
 async def save_listing(self,x:CarListing):
  async with self.pool.acquire() as c:
   r=await c.fetchrow('''INSERT INTO listings(source,source_id,url,brand,model,brand_id,model_id,generation,year,mileage_km,price_usd,city,seller_type,title,description,published_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16) ON CONFLICT(source,source_id) DO UPDATE SET last_seen_at=NOW(),price_usd=EXCLUDED.price_usd,description=EXCLUDED.description RETURNING xmax=0 AS inserted''',x.source,x.source_id,x.url,x.brand,x.model,x.brand_id,x.model_id,x.generation,x.year,x.mileage_km,x.price_usd,x.city,x.seller_type,x.title,x.description,x.published_at)
   return bool(r['inserted'])
 async def get_market_cache(self,key:str,hours:int):
  async with self.pool.acquire() as c:
   r=await c.fetchrow("SELECT median_usd FROM market_cache WHERE cache_key=$1 AND cached_at>=NOW()-($2*INTERVAL '1 hour')",key,hours)
   return float(r['median_usd']) if r and r['median_usd'] is not None else None
 async def set_market_cache(self,key:str,value:float):
  async with self.pool.acquire() as c: await c.execute('INSERT INTO market_cache(cache_key,median_usd) VALUES($1,$2) ON CONFLICT(cache_key) DO UPDATE SET median_usd=EXCLUDED.median_usd,cached_at=NOW()',key,value)
