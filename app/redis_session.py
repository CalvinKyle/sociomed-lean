import redis
import time
import uuid

class RedisSessionManager:
    def __init__(self, host='localhost', port=6379, db=0):
        self.redis_client = redis.StrictRedis(host=host, port=port, db=db)

    def create_session(self, user_id, ttl=3600):
        session_id = str(uuid.uuid4())
        lock_key = f'session_lock:{session_id}'
        self.redis_client.set(lock_key, "lock", ex=ttl, nx=True)  # set lock if not exists

        self.redis_client.setex(session_id, ttl, user_id)  # store user_id with a TTL
        return session_id

    def get_session(self, session_id):
        user_id = self.redis_client.get(session_id)
        return user_id.decode('utf-8') if user_id else None

    def delete_session(self, session_id):
        self.redis_client.delete(session_id)

    def extend_session(self, session_id, ttl):
        if self.redis_client.exists(session_id):
            self.redis_client.expire(session_id, ttl)

    def acquire_lock(self, session_id, timeout=60):
        lock_key = f'session_lock:{session_id}'
        lock_acquired = self.redis_client.set(lock_key, "lock", ex=timeout, nx=True)
        return lock_acquired

    def release_lock(self, session_id):
        lock_key = f'session_lock:{session_id}'
        self.redis_client.delete(lock_key)

# Example usage
if __name__ == "__main__":
    session_manager = RedisSessionManager()
    session_id = session_manager.create_session(user_id="user123")
    print(f"Session created: {session_id}")
