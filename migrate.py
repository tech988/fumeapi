import os

from pymongo import MongoClient
from bson import ObjectId

MONGO_URI = os.environ["MONGO_URI"]
DB_NAME = "hb"
COL_NAME = "packages"  # change

client = MongoClient(MONGO_URI)
col = client[DB_NAME][COL_NAME]

res = col.update_many(
    {"image": {"$type": "objectId"}},
    [{"$set": {"image": {"$toString": "$image"}}}],
)

print("matched:", res.matched_count, "modified:", res.modified_count)
