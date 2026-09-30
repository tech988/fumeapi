# app/core/db.py
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

from pymongo import MongoClient
from gridfs import GridFSBucket

client: AsyncIOMotorClient | None = None
pymongo_client: MongoClient | None = None
gridfs_bucket: GridFSBucket | None = None


def get_client() -> AsyncIOMotorClient:
    # Serverless runtimes (Vercel) may skip startup events, so connect lazily.
    if client is None:
        _init_clients()
    return client


def get_db():
    return get_client()[settings.MONGO_DB]


def get_gridfs_bucket() -> GridFSBucket:
    if gridfs_bucket is None:
        _init_clients()
    return gridfs_bucket


async def connect_mongo():
    if client is None:
        _init_clients()


def _init_clients():
    global client, pymongo_client, gridfs_bucket

    # Motor (async) – your existing usage
    client = AsyncIOMotorClient(settings.MONGO_URI)

    # PyMongo (sync) – for GridFSBucket streaming
    pymongo_client = MongoClient(settings.MONGO_URI)
    pymongo_db = pymongo_client[settings.MONGO_DB]

    # bucketName = "images" -> creates images.files and images.chunks
    gridfs_bucket = GridFSBucket(pymongo_db, bucket_name="images")


async def close_mongo():
    global client, pymongo_client, gridfs_bucket

    if client:
        client.close()
        client = None

    if pymongo_client:
        pymongo_client.close()
        pymongo_client = None

    gridfs_bucket = None
