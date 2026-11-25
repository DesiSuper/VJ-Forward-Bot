
import motor.motor_asyncio


class MongoDB:
    def __init__(self, uri, db_name, collection):
        self.uri = uri
        self.db_name = db_name
        self.collection = collection 
        self.client = None
        self.db = None
        self.files = None

    async def connect(self):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(
            self.uri,
            serverSelectionTimeoutMS=5_000,
            connectTimeoutMS=5_000,
        )
        self.db = self.client[self.db_name]
        self.files = self.db[self.collection]
        await self.client.admin.command("ping")
        await self.files.create_index("file_unique_id", unique=True, sparse=True)

    async def close(self):
        if self.client:
            self.client.close()

    async def add_file(self, file_unique_id):
        return await self.files.update_one(
            {"file_unique_id": file_unique_id},
            {"$setOnInsert": {"file_unique_id": file_unique_id}},
            upsert=True,
        )

    async def is_file_exit(self, file_unique_id):
        existing = await self.files.find_one({"file_unique_id": file_unique_id}, {"_id": 1})
        return existing is not None

    async def get_all_files(self):
        """Return Motor's async cursor, including legacy file_id-only entries."""
        return self.files.find({})
        

async def connect_user_db(user_id, uri, chat):
    chat = f"{user_id}{chat}"
    dbname = f"{user_id}-Forward-Bot"
    db = MongoDB(uri, dbname, chat)
    try:
        await db.connect()
    except Exception:
        await db.close()
        return False, db
    return True, db
