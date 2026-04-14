import redis

class RedisCache:
    def __init__(self, host='localhost', port=6379, db=0):
        self.client = redis.StrictRedis(host=host, port=port, db=db, decode_responses=True)

    def set(self, key, value, ttl=None):
        self.client.set(key, value, ex=ttl)

    def get(self, key):
        return self.client.get(key)

    def invalidate(self, key):
        self.client.delete(key)

# Example usage
if __name__ == '__main__':
    cache = RedisCache()
    # Cache product data
    cache.set('product:1', 'Product details here', ttl=3600) # TTL for 1 hour
    # Fetch from cache
    product = cache.get('product:1')
    print(product)
    # Invalidate cache
    cache.invalidate('product:1')