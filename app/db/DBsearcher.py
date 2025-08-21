import aiosqlite

class DBsearcher:
    def __init__(self, db_path):
        self.db_path=db_path

    async def main(self, username, user_id):
        async with aiosqlite.connect(self.db_path, loop=None) as cursor:
            await cursor.execute('''
                CREATE TABLE users(
                    id serial PRIMARY KEY,
                    username,
                    id
                )
            ''')

            await cursor.execute(f"INSERT INTO users (name, age) VALUES (?, ?), ({username}, {user_id})")

            cursor.commit()

            rows = await cursor.fetchall()
            for row in rows:
                print(row)
            
            await cursor.close()

    async def add_user(self, username, user_id):
        await self.main(username, user_id)