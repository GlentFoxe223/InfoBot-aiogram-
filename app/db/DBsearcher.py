import asyncio
import asyncpg

class DBsearcher:
    def __init__(self, db_path):
        self.db_path=db_path

    async def main(self, username, user_id):
        async with asyncpg.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE users(
                    id serial PRIMARY KEY,
                    username,
                    id
                )
            ''')

            await db.execute('''
                INSERT INTO users(username, id) VALUES($1, $2)
            ''', username, user_id)
            
            await db.close()

    def add_user(self, username, user_id):
        asyncio.run(self.main(username, user_id))