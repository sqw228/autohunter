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
CREATE TABLE IF NOT EXISTS subscribers (
 chat_id BIGINT PRIMARY KEY,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS subscriber_settings (
 chat_id BIGINT PRIMARY KEY REFERENCES subscribers(chat_id) ON DELETE CASCADE,
 min_year INTEGER NOT NULL DEFAULT 2012,
 min_discount DOUBLE PRECISION NOT NULL DEFAULT 15,
 max_mileage_km INTEGER,
 max_price_usd DOUBLE PRECISION,
 brand_id INTEGER,
 brand_name TEXT,
 model_id INTEGER,
 model_name TEXT,
 region_id INTEGER,
 region_name TEXT
);
CREATE TABLE IF NOT EXISTS sent_notifications (
 chat_id BIGINT NOT NULL REFERENCES subscribers(chat_id) ON DELETE CASCADE,
 source TEXT NOT NULL,
 source_id TEXT NOT NULL,
 sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(chat_id, source, source_id)
);
CREATE TABLE IF NOT EXISTS market_cache (cache_key TEXT PRIMARY KEY, median_usd DOUBLE PRECISION,
 cached_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE IF NOT EXISTS favorites (
 chat_id BIGINT NOT NULL REFERENCES subscribers(chat_id) ON DELETE CASCADE,
 source TEXT NOT NULL, source_id TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(chat_id, source, source_id)
);
CREATE TABLE IF NOT EXISTS app_preferences (
 chat_id BIGINT PRIMARY KEY REFERENCES subscribers(chat_id) ON DELETE CASCADE,
 language TEXT NOT NULL DEFAULT 'ru'
);
CREATE TABLE IF NOT EXISTS catalog_cache (
 kind TEXT NOT NULL,
 parent_id INTEGER NOT NULL DEFAULT 0,
 item_id INTEGER NOT NULL,
 name TEXT NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(kind, parent_id, item_id)
);
'''


class Database:
    def __init__(self, url: str):
        self.url = url
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(self.url, min_size=1, max_size=5)
        async with self.pool.acquire() as c:
            await c.execute(CREATE_SQL)
            await c.execute(
                'ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS '
                'notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE'
            )
            for sql in (
                'ALTER TABLE subscriber_settings ADD COLUMN IF NOT EXISTS brand_id INTEGER',
                'ALTER TABLE subscriber_settings ADD COLUMN IF NOT EXISTS brand_name TEXT',
                'ALTER TABLE subscriber_settings ADD COLUMN IF NOT EXISTS model_id INTEGER',
                'ALTER TABLE subscriber_settings ADD COLUMN IF NOT EXISTS model_name TEXT',
                'ALTER TABLE subscriber_settings ADD COLUMN IF NOT EXISTS region_id INTEGER',
                'ALTER TABLE subscriber_settings ADD COLUMN IF NOT EXISTS region_name TEXT',
                'ALTER TABLE subscriber_settings ADD COLUMN IF NOT EXISTS transmission TEXT',
                'ALTER TABLE subscriber_settings ADD COLUMN IF NOT EXISTS fuel TEXT',
                'ALTER TABLE listings ADD COLUMN IF NOT EXISTS transmission TEXT',
                'ALTER TABLE listings ADD COLUMN IF NOT EXISTS fuel TEXT',
            ):
                await c.execute(sql)
            await c.execute('''
                INSERT INTO app_preferences(chat_id)
                SELECT chat_id FROM subscribers
                ON CONFLICT(chat_id) DO NOTHING
            ''')
            await c.execute('''
                INSERT INTO subscriber_settings(chat_id)
                SELECT chat_id FROM subscribers
                ON CONFLICT(chat_id) DO NOTHING
            ''')

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def add_subscriber(self, chat_id: int):
        async with self.pool.acquire() as c:
            await c.execute(
                'INSERT INTO subscribers(chat_id) VALUES($1) ON CONFLICT(chat_id) DO NOTHING', chat_id
            )
            await c.execute(
                'INSERT INTO subscriber_settings(chat_id) VALUES($1) ON CONFLICT(chat_id) DO NOTHING', chat_id
            )

    async def subscribers(self):
        async with self.pool.acquire() as c:
            return [int(r['chat_id']) for r in await c.fetch(
                'SELECT chat_id FROM subscribers WHERE notifications_enabled=TRUE'
            )]

    async def subscriber_settings(self):
        async with self.pool.acquire() as c:
            rows = await c.fetch('''
                SELECT s.chat_id, ss.min_year, ss.min_discount,
                       ss.max_mileage_km, ss.max_price_usd,
                       ss.brand_id, ss.brand_name, ss.model_id, ss.model_name,
                       ss.region_id, ss.region_name, ss.transmission, ss.fuel
                FROM subscribers s
                JOIN subscriber_settings ss ON ss.chat_id=s.chat_id
                WHERE s.notifications_enabled=TRUE
            ''')
            return [dict(r) for r in rows]

    async def notifications_enabled(self, chat_id: int):
        async with self.pool.acquire() as c:
            r = await c.fetchrow(
                'SELECT notifications_enabled FROM subscribers WHERE chat_id=$1', chat_id
            )
            return bool(r['notifications_enabled']) if r else True

    async def toggle_notifications(self, chat_id: int):
        async with self.pool.acquire() as c:
            r = await c.fetchrow(
                'UPDATE subscribers SET notifications_enabled=NOT notifications_enabled '
                'WHERE chat_id=$1 RETURNING notifications_enabled', chat_id
            )
            return bool(r['notifications_enabled']) if r else True

    async def get_settings(self, chat_id: int):
        async with self.pool.acquire() as c:
            r = await c.fetchrow(
                '''SELECT min_year, min_discount, max_mileage_km, max_price_usd,
                          brand_id, brand_name, model_id, model_name, region_id, region_name,
                          transmission, fuel
                   FROM subscriber_settings WHERE chat_id=$1''', chat_id
            )
            return dict(r) if r else {
                'min_year': 2012, 'min_discount': 15.0,
                'max_mileage_km': None, 'max_price_usd': None,
                'brand_id': None, 'brand_name': None,
                'model_id': None, 'model_name': None,
                'region_id': None, 'region_name': None,
                'transmission': None, 'fuel': None,
            }

    async def update_setting(self, chat_id: int, field: str, value):
        allowed = {
            'min_year', 'min_discount', 'max_mileage_km', 'max_price_usd',
            'brand_id', 'brand_name', 'model_id', 'model_name',
            'region_id', 'region_name', 'transmission', 'fuel',
        }
        if field not in allowed:
            raise ValueError('Unknown setting')
        async with self.pool.acquire() as c:
            await c.execute(
                f'UPDATE subscriber_settings SET {field}=$1 WHERE chat_id=$2', value, chat_id
            )

    async def set_brand(self, chat_id: int, brand_id, brand_name):
        async with self.pool.acquire() as c:
            await c.execute(
                '''UPDATE subscriber_settings
                   SET brand_id=$1, brand_name=$2, model_id=NULL, model_name=NULL
                   WHERE chat_id=$3''', brand_id, brand_name, chat_id
            )

    async def set_model(self, chat_id: int, model_id, model_name):
        async with self.pool.acquire() as c:
            await c.execute(
                'UPDATE subscriber_settings SET model_id=$1, model_name=$2 WHERE chat_id=$3',
                model_id, model_name, chat_id
            )

    async def set_region(self, chat_id: int, region_id, region_name):
        async with self.pool.acquire() as c:
            await c.execute(
                'UPDATE subscriber_settings SET region_id=$1, region_name=$2 WHERE chat_id=$3',
                region_id, region_name, chat_id
            )

    async def was_notified(self, chat_id: int, source: str, source_id: str):
        async with self.pool.acquire() as c:
            r = await c.fetchrow(
                'SELECT 1 FROM sent_notifications WHERE chat_id=$1 AND source=$2 AND source_id=$3',
                chat_id, source, source_id
            )
            return r is not None

    async def mark_user_notified(self, chat_id: int, source: str, source_id: str):
        async with self.pool.acquire() as c:
            await c.execute(
                'INSERT INTO sent_notifications(chat_id,source,source_id) VALUES($1,$2,$3) '
                'ON CONFLICT(chat_id,source,source_id) DO NOTHING', chat_id, source, source_id
            )

    async def save_listing(self, x: CarListing):
        async with self.pool.acquire() as c:
            r = await c.fetchrow(
                '''INSERT INTO listings(
                    source,source_id,url,brand,model,brand_id,model_id,generation,year,
                    mileage_km,price_usd,city,seller_type,title,description,published_at,transmission,fuel
                ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
                ON CONFLICT(source,source_id) DO UPDATE SET
                    last_seen_at=NOW(), url=EXCLUDED.url, price_usd=EXCLUDED.price_usd,
                    mileage_km=EXCLUDED.mileage_km, description=EXCLUDED.description,
                    transmission=EXCLUDED.transmission, fuel=EXCLUDED.fuel
                RETURNING xmax=0 AS inserted, notified''',
                x.source, x.source_id, x.url, x.brand, x.model, x.brand_id, x.model_id,
                x.generation, x.year, x.mileage_km, x.price_usd, x.city, x.seller_type,
                x.title, x.description, x.published_at, x.transmission, x.fuel,
            )
            return bool(r['inserted']), bool(r['notified'])

    async def mark_notified(self, source: str, source_id: str):
        async with self.pool.acquire() as c:
            await c.execute(
                'UPDATE listings SET notified=TRUE WHERE source=$1 AND source_id=$2', source, source_id
            )

    async def set_catalog_cache(self, kind: str, parent_id: int, items):
        async with self.pool.acquire() as c:
            await c.execute('DELETE FROM catalog_cache WHERE kind=$1 AND parent_id=$2', kind, parent_id)
            if items:
                await c.executemany(
                    'INSERT INTO catalog_cache(kind,parent_id,item_id,name) VALUES($1,$2,$3,$4) '
                    'ON CONFLICT(kind,parent_id,item_id) DO UPDATE SET name=EXCLUDED.name,updated_at=NOW()',
                    [(kind, parent_id, int(item_id), str(name)) for name, item_id in items]
                )

    async def get_catalog_cache(self, kind: str, parent_id: int = 0):
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                'SELECT name,item_id FROM catalog_cache WHERE kind=$1 AND parent_id=$2 ORDER BY name',
                kind, parent_id
            )
            return [(r['name'], int(r['item_id'])) for r in rows]

    async def find_catalog(self, kind: str, query: str, parent_id: int = 0):
        q = (query or '').strip().lower()
        items = await self.get_catalog_cache(kind, parent_id)
        if not q:
            return items
        return [x for x in items if q in x[0].lower()]

    async def get_market_cache(self, key: str, hours: int):
        async with self.pool.acquire() as c:
            r = await c.fetchrow(
                "SELECT median_usd FROM market_cache WHERE cache_key=$1 "
                "AND cached_at>=NOW()-($2*INTERVAL '1 hour')", key, hours
            )
            return float(r['median_usd']) if r and r['median_usd'] is not None else None

    async def set_market_cache(self, key: str, value: float):
        async with self.pool.acquire() as c:
            await c.execute(
                'INSERT INTO market_cache(cache_key,median_usd) VALUES($1,$2) '
                'ON CONFLICT(cache_key) DO UPDATE SET median_usd=EXCLUDED.median_usd,cached_at=NOW()',
                key, value
            )


    async def get_listings_for_user(self, chat_id: int, limit: int = 100):
        async with self.pool.acquire() as c:
            return [dict(r) for r in await c.fetch('''
                SELECT l.*, mc.median_usd,
                       CASE WHEN mc.median_usd IS NOT NULL AND mc.median_usd > 0
                            THEN ROUND(((1 - l.price_usd / mc.median_usd) * 100)::numeric, 1)
                            ELSE NULL END AS discount_percent,
                       EXISTS(
                         SELECT 1 FROM favorites f
                         WHERE f.chat_id=$1 AND f.source=l.source AND f.source_id=l.source_id
                       ) AS is_favorite
                FROM listings l
                LEFT JOIN market_cache mc
                  ON mc.cache_key = ('ria:' || COALESCE(l.brand_id,0) || ':' ||
                                     COALESCE(l.model_id,0) || ':' || COALESCE(l.year,0))
                JOIN subscriber_settings ss ON ss.chat_id=$1
                WHERE l.price_usd IS NOT NULL
                  AND (ss.brand_id IS NULL OR l.brand_id=ss.brand_id)
                  AND (ss.model_id IS NULL OR l.model_id=ss.model_id)
                  AND (l.year IS NULL OR l.year >= ss.min_year)
                  AND (ss.max_mileage_km IS NULL OR l.mileage_km IS NULL OR l.mileage_km <= ss.max_mileage_km)
                  AND (ss.max_price_usd IS NULL OR l.price_usd <= ss.max_price_usd)
                  AND (ss.transmission IS NULL OR LOWER(COALESCE(l.transmission,'')) LIKE LOWER('%' || ss.transmission || '%'))
                  AND (ss.fuel IS NULL OR LOWER(COALESCE(l.fuel,'')) LIKE LOWER('%' || ss.fuel || '%'))
                  AND (mc.median_usd IS NULL OR l.price_usd <= mc.median_usd * (1 - ss.min_discount / 100.0))
                ORDER BY l.first_seen_at DESC
                LIMIT $2
            ''', chat_id, limit)]

    async def get_favorites(self, chat_id: int, limit: int = 100):
        async with self.pool.acquire() as c:
            return [dict(r) for r in await c.fetch('''
                SELECT l.*, mc.median_usd,
                       CASE WHEN mc.median_usd IS NOT NULL AND mc.median_usd > 0
                            THEN ROUND(((1 - l.price_usd / mc.median_usd) * 100)::numeric, 1)
                            ELSE NULL END AS discount_percent,
                       TRUE AS is_favorite
                FROM favorites f
                JOIN listings l ON l.source=f.source AND l.source_id=f.source_id
                LEFT JOIN market_cache mc
                  ON mc.cache_key = ('ria:' || COALESCE(l.brand_id,0) || ':' ||
                                     COALESCE(l.model_id,0) || ':' || COALESCE(l.year,0))
                WHERE f.chat_id=$1
                ORDER BY f.created_at DESC
                LIMIT $2
            ''', chat_id, limit)]

    async def set_favorite(self, chat_id: int, source: str, source_id: str, value: bool):
        async with self.pool.acquire() as c:
            if value:
                await c.execute('''
                    INSERT INTO favorites(chat_id,source,source_id)
                    VALUES($1,$2,$3) ON CONFLICT DO NOTHING
                ''', chat_id, source, source_id)
            else:
                await c.execute(
                    'DELETE FROM favorites WHERE chat_id=$1 AND source=$2 AND source_id=$3',
                    chat_id, source, source_id
                )

    async def get_stats(self, chat_id: int):
        async with self.pool.acquire() as c:
            r = await c.fetchrow('''
                SELECT
                  COUNT(*) FILTER (WHERE l.first_seen_at >= NOW()-INTERVAL '24 hours') AS found_today,
                  COUNT(*) FILTER (
                    WHERE l.first_seen_at >= NOW()-INTERVAL '24 hours'
                      AND mc.median_usd IS NOT NULL AND l.price_usd < mc.median_usd
                  ) AS below_market_today,
                  AVG(CASE WHEN mc.median_usd IS NOT NULL AND mc.median_usd > 0
                           THEN (1 - l.price_usd / mc.median_usd) * 100 END)
                    FILTER (WHERE l.first_seen_at >= NOW()-INTERVAL '24 hours'
                            AND mc.median_usd IS NOT NULL) AS avg_discount,
                  MAX(CASE WHEN mc.median_usd IS NOT NULL AND mc.median_usd > 0
                           THEN (1 - l.price_usd / mc.median_usd) * 100 END)
                    FILTER (WHERE l.first_seen_at >= NOW()-INTERVAL '24 hours'
                            AND mc.median_usd IS NOT NULL) AS max_discount,
                  (SELECT COUNT(*) FROM favorites WHERE favorites.chat_id=$1) AS favorites_count
                FROM listings l
                LEFT JOIN market_cache mc
                  ON mc.cache_key = ('ria:' || COALESCE(l.brand_id,0) || ':' ||
                                     COALESCE(l.model_id,0) || ':' || COALESCE(l.year,0))
            ''', chat_id)
            return dict(r)

    async def get_language(self, chat_id: int):
        async with self.pool.acquire() as c:
            r = await c.fetchrow('SELECT language FROM app_preferences WHERE chat_id=$1', chat_id)
            return r['language'] if r else 'ru'

    async def set_language(self, chat_id: int, language: str):
        if language not in {'ru', 'uk', 'en'}:
            raise ValueError('Unsupported language')
        async with self.pool.acquire() as c:
            await c.execute('''
                INSERT INTO app_preferences(chat_id,language) VALUES($1,$2)
                ON CONFLICT(chat_id) DO UPDATE SET language=EXCLUDED.language
            ''', chat_id, language)
